"""Read saved QQ evidence across Experience and legacy Perception stores."""
import json
import sqlite3
from pathlib import Path

from .models import CognitiveEvent, CognitiveEventType, EventPart


def decode_media(value, media):
    if isinstance(value, dict) and "$media" in value:
        try:
            return media.decode(value)
        except (OSError, ValueError):
            return None
    if isinstance(value, dict):
        return {key: decode_media(item, media) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_media(item, media) for item in value]
    return value


class SocialHistory:
    def __init__(self, stream, perception_path=None):
        self.stream = stream
        self.perception_path = Path(perception_path) if perception_path else None

    def _perception(self):
        if not self.perception_path or not self.perception_path.is_file():
            return None
        db = sqlite3.connect(self.perception_path.resolve().as_uri() + "?mode=ro", uri=True)
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations'").fetchone():
            db.close()
            return None
        return db

    @staticmethod
    def observation_event(item):
        refs = item.get("metadata", {}).get("merged_refs") or ([item["raw_ref"]] if item.get("raw_ref") else [])
        parts = item.get("parts") or [
            {"type": a["type"], "url": a.get("url"), "file": a.get("file")}
            for a in item.get("attachments", []) if a.get("type") == "image"]
        return CognitiveEvent(
            event_id="observation:" + item["observation_id"],
            event_type=CognitiveEventType.EXTERNAL_MESSAGE,
            source=item["source"], channel=item["source"],
            session_id=f"{item['source']}/{item.get('conversation_kind')}/{item.get('conversation_id')}",
            conversation_id=item.get("conversation_id"), actor_id=item.get("actor_id"),
            actor_name=item.get("actor_name"), actor_role=item.get("actor_role"),
            content=item.get("content", ""), parts=[EventPart.model_validate(p) for p in parts],
            occurred_at=item["occurred_at"], received_at=item["received_at"],
            privacy_level="SOCIAL" if item.get("conversation_kind") == "group" else "OWNER_PRIVATE",
            trust_level=item.get("trust_level", "UNVERIFIED"), source_refs=refs,
            metadata={**item.get("metadata", {}), "conversation_kind": item.get("conversation_kind"),
                      "source_plugin": item.get("source_plugin"), "evidence_store": "perception"})

    def find(self, reference, source=None):
        db = self._perception()
        if db is None:
            return None
        try:
            if reference.startswith("snapshot:"):
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'").fetchone():
                    return None
                row = db.execute("SELECT payload FROM snapshots WHERE id=?", (reference[9:],)).fetchone()
                if not row:
                    return None
                snap = json.loads(row[0])
                if source is not None and source != snap["source"]:
                    return None
                ids = snap.get("observation_ids", [])
                # Keep only real saved citations; never invent sentence-level evidence.
                items = {}
                for start in range(0, len(ids), 200):
                    chunk = ids[start:start + 200]
                    rows = db.execute("SELECT id,payload FROM observations WHERE id IN (" +
                                      ",".join("?" for _ in chunk) + ")", chunk).fetchall()
                    items.update((key, json.loads(payload)) for key, payload in rows)
                plugins = {item.get("source_plugin") for item in items.values()}
                if any(item.get("source") != snap["source"] or item.get("conversation_kind") != "group"
                       or item.get("conversation_id") != snap["conversation_id"] for item in items.values()) or len(plugins) > 1:
                    return None
                statements = [{"statement_id": f"s{i+1}", "text": statement["text"],
                               "raw_refs": [items[key]["raw_ref"] for key in statement["evidence_observation_ids"]
                                            if key in items and items[key].get("raw_ref")]}
                              for i, statement in enumerate(snap.get("statements", []))]
                return CognitiveEvent(
                    event_id=reference, event_type=CognitiveEventType.SOCIAL_SNAPSHOT,
                    source=snap["source"], channel=snap["source"],
                    session_id=f"{snap['source']}/group/{snap['conversation_id']}",
                    conversation_id=snap["conversation_id"], actor_role="SELF", privacy_level="SOCIAL",
                    content=snap["summary"], occurred_at=snap["window_end"], received_at=snap["window_end"],
                    source_refs=[reference], parent_refs=snap.get("raw_refs", []),
                    metadata={"conversation_kind": "group", "source_plugin": next(iter(plugins), None),
                              "social_statements": statements, "evidence_store": "perception"})
            if reference.startswith("observation:"):
                rows = db.execute("SELECT payload FROM observations WHERE id=? AND status!='IGNORED'", (reference[12:],)).fetchall()
            else:
                rows = db.execute("SELECT payload FROM observations WHERE raw_ref=? AND status!='IGNORED'" +
                                  (" AND source=?" if source is not None else "") + " LIMIT 2",
                                  (reference, source) if source is not None else (reference,)).fetchall()
            if len(rows) != 1:
                return None
            item = decode_media(json.loads(rows[0][0]), self.stream.media)
            if source is not None and item["source"] != source:
                return None
            return self.observation_event(item)
        finally:
            db.close()

    def search(self, *, query=None, group_id=None, source_plugin=None, since=None, until=None,
               offset=0, limit=8):
        """SQL filters all saved history before pagination, not the recent 200 events."""
        db = sqlite3.connect(Path(self.stream.path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            attached = bool(self.perception_path and self.perception_path.is_file())
            if attached:
                db.execute("ATTACH DATABASE ? AS social_legacy",
                           (self.perception_path.resolve().as_uri() + "?mode=ro",))
                attached = bool(db.execute("SELECT 1 FROM social_legacy.sqlite_master WHERE type='table' AND name='observations'").fetchone())
            # Expand saved direct-message bursts without losing per-message boundaries.
            sql = """WITH sources AS (
                SELECT event_id AS id, payload, 0 AS priority FROM events
                WHERE source='qq' AND event_type='EXTERNAL_MESSAGE'
            """
            if attached:
                sql += """ UNION ALL SELECT 'observation:'||id, payload, 1
                    FROM social_legacy.observations WHERE source='qq'
                    AND json_extract(payload,'$.conversation_kind')='group' AND status!='IGNORED' """
            sql += """), expanded AS (
                SELECT s.id, s.payload AS parent, j.value AS item, s.priority
                FROM sources s, json_each(CASE
                    WHEN json_array_length(s.payload,'$.metadata.raw_observations')>0
                    THEN json_extract(s.payload,'$.metadata.raw_observations')
                    ELSE json_array(json(s.payload)) END) j
            ), messages AS (
                SELECT *, COALESCE(json_extract(item,'$.raw_ref'),
                    CASE WHEN json_array_length(parent,'$.source_refs')=1
                         THEN json_extract(parent,'$.source_refs[0]') ELSE id END) AS ref,
                    COALESCE(json_extract(item,'$.conversation_id'),json_extract(parent,'$.conversation_id'),
                        CASE WHEN json_extract(parent,'$.session_id') LIKE 'qq/group/%'
                             THEN substr(json_extract(parent,'$.session_id'),10) END) AS group_id,
                    COALESCE(json_extract(item,'$.source_plugin'),json_extract(parent,'$.metadata.source_plugin')) AS plugin,
                    COALESCE(json_extract(item,'$.occurred_at'),json_extract(parent,'$.occurred_at')) AS occurred,
                    CASE WHEN json_type(item,'$.metadata.raw_message.message')='text'
                         THEN json_extract(item,'$.metadata.raw_message.message')
                         WHEN json_type(item,'$.metadata.raw_message.message')='array'
                         THEN COALESCE((SELECT group_concat(CASE json_extract(value,'$.type')
                             WHEN 'text' THEN COALESCE(json_extract(value,'$.data.text'),'')
                             WHEN 'at' THEN '@'||COALESCE(json_extract(value,'$.data.qq'),'') ELSE '' END,'')
                             FROM json_each(item,'$.metadata.raw_message.message')),'')
                         ELSE COALESCE(json_extract(item,'$.content'),'') END AS text
                FROM expanded WHERE COALESCE(json_extract(item,'$.conversation_kind'),
                    json_extract(parent,'$.metadata.conversation_kind'),
                    CASE WHEN json_extract(parent,'$.session_id') LIKE 'qq/group/%' THEN 'group' END)='group'
            ), ranked AS (
                SELECT *, row_number() OVER (PARTITION BY ref ORDER BY priority,id) AS rn FROM messages
            ), matches AS (SELECT * FROM ranked WHERE rn=1
                AND COALESCE(json_extract(parent,'$.privacy_level'),'SOCIAL')='SOCIAL' """
            args = []
            for condition, value in [("group_id=?", group_id), ("plugin=?", source_plugin),
                                     ("julianday(occurred)>=julianday(?)", since),
                                     ("julianday(occurred)<julianday(?)", until),
                                     ("instr(lower(text),lower(?))>0", query)]:
                if value is not None:
                    sql += " AND " + condition
                    args.append(value.isoformat() if hasattr(value, "isoformat") else value)
            sql += ") SELECT ref,id,count(*) OVER() AS total FROM matches ORDER BY julianday(occurred) DESC,ref DESC LIMIT ? OFFSET ?"
            return db.execute(sql, [*args, limit, offset]).fetchall()
        finally:
            db.close()
