"""Bounded social evidence expansion; summaries are never returned as raw speech."""
import json
from collections import deque
from .models import CognitiveEvent, CognitiveEventType
from .provenance import from_event
from .social_history import SocialHistory, decode_media


def social_access(event, turn=None):
    origin = from_event(event)
    if origin.conversation_kind != "group" or event.privacy_level != "SOCIAL":
        return False
    if turn is None or turn.output_channel == "desktop":
        return True
    current = from_event(turn.trigger_event)
    if (turn.output_channel in {"web", "cli", "voice"} and turn.audience == "owner"
            and current.channel == turn.output_channel and current.actor_role == "OWNER"):
        return True
    return (current.conversation_kind == "group" and bool(current.session_id)
            and bool(current.conversation_id) and origin.channel == current.channel
            and origin.session_id == current.session_id
            and origin.conversation_id == current.conversation_id
            and origin.source_plugin == current.source_plugin)


class SocialTraceReader:
    EVIDENCE_TYPES = {CognitiveEventType.EXTERNAL_MESSAGE, CognitiveEventType.USER_MESSAGE,
                      CognitiveEventType.SOCIAL_SNAPSHOT}

    def __init__(self, stream, perception_path=None):
        self.stream = stream
        self.history = SocialHistory(stream, perception_path)

    def _load_event(self, event_id):
        with self.stream._connect() as db:
            row = db.execute("SELECT payload FROM events WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            return None
        return CognitiveEvent.model_validate(decode_media(json.loads(row[0]), self.stream.media))

    def find(self, reference, source=None):
        event = self._load_event(reference)
        if event is not None:
            return event if source is None or event.source == source else None
        with self.stream._connect() as db:
            sql = "SELECT event_id FROM event_refs WHERE source_ref=?"
            args = [reference]
            if source is not None:
                sql += " AND source=?"
                args.append(source)
            rows = db.execute(sql + " LIMIT 2",args).fetchall()
        if rows:
            return self._load_event(rows[0][0]) if len(rows) == 1 else None
        fallback = self.history.find(reference, source)
        if fallback is not None and fallback.event_type == CognitiveEventType.EXTERNAL_MESSAGE and fallback.source_refs:
            # A legacy observation ID must not bypass an existing event's privacy classification.
            marks = ",".join("?" for _ in fallback.source_refs)
            with self.stream._connect() as db:
                primary = db.execute("SELECT event_id FROM event_refs WHERE source=? AND source_ref IN (" +
                                     marks + ") LIMIT 1", (fallback.source, *fallback.source_refs)).fetchone()
            if primary:
                return self._load_event(primary[0])
        return fallback

    @staticmethod
    def original_text(content, raw_message):
        if not isinstance(raw_message,dict):return content
        parts=raw_message.get("message")
        if isinstance(parts,str):return parts
        if not isinstance(parts,list):return content
        return "".join(str(p.get("data",{}).get("text", "")) if p.get("type")=="text" else "@"+str(p.get("data",{}).get("qq", "")) if p.get("type")=="at" else "" for p in parts if isinstance(p,dict))

    @staticmethod
    def originals(event, requested_ref=None):
        origin = from_event(event).metadata()
        originals = event.metadata.get("raw_observations") or []
        if originals:
            return [{"event_id":event.event_id,"raw_ref":item.get("raw_ref"),
                "content":item.get("content", ""), "parts":item.get("parts", []),
                "raw_message":item.get("metadata",{}).get("raw_message"),
                "original_kind":"message", "evidence_store":event.metadata.get("evidence_store", "experience"), "provenance":{**origin,
                    "origin_actor_id":item.get("actor_id"),"origin_actor_name":item.get("actor_name"),
                    "origin_actor_role":item.get("actor_role"),"origin_occurred_at":item.get("occurred_at")}}
                for item in originals if requested_ref is None or item.get("raw_ref")==requested_ref]
        return [{"event_id":event.event_id,"raw_ref":event.source_refs[0] if len(event.source_refs)==1 else None,
            "raw_refs":event.source_refs,"content":event.content or "", "parts":[p.model_dump() for p in event.parts],
            "raw_message":event.metadata.get("raw_message"),"provenance":origin,
            "evidence_store":event.metadata.get("evidence_store", "experience"),
            "original_kind":"merged_legacy" if len(event.source_refs)>1 else "message"}]

    def read(self, reference, *, statement_id=None, offset=0, limit=8, max_chars=6000, text_offset=0, turn=None):
        unit = self.stream.load_timeline_unit(reference)
        seed = unit.get("source_event_ids",[]) if unit else [reference]
        statements = unit.get("social_statements",[]) if unit else []
        first = [self.find(ref) for ref in seed]
        if unit:
            # A turn also contains replies and tool transcripts. Only incoming
            # messages and snapshots can be the original social evidence.
            seed = [ref for ref, event in zip(seed, first)
                    if event is None or event.event_type in self.EVIDENCE_TYPES]
            first = [event for event in first
                     if event is None or event.event_type in self.EVIDENCE_TYPES]
        if any(e is not None and not social_access(e,turn) for e in first):
            return {"status":"forbidden","reference":reference,"records":[]}
        if not statements:
            statements = [s for e in first if e is not None for s in e.metadata.get("social_statements",[])]
        if statement_id:
            statement = next((s for s in statements if s.get("statement_id")==statement_id),None)
            if statement is None:
                return {"status":"statement_not_found","reference":reference,"granularity":"batch" if not statements else "statement","records":[]}
            seed = statement.get("raw_refs",[]) + statement.get("source_event_ids",[])
        queue = deque((ref,None,0) for ref in seed)
        seen, rows, keys, missing = set(), [], set(), []
        while queue and len(seen)<500:
            ref,source,depth = queue.popleft()
            if (ref,source) in seen:
                continue
            seen.add((ref,source))
            event = self.find(ref,source)
            if event is None:
                missing.append(ref)
                continue
            if not social_access(event,turn):
                return {"status":"forbidden","reference":reference,"records":[]}
            if event.event_type == CognitiveEventType.SOCIAL_SNAPSHOT:
                if depth >= 8:
                    missing.append(ref)
                    continue
                children = event.parent_refs
                if not children:
                    missing.append(ref)
                queue.extend((child,event.source,depth+1) for child in children)
                continue
            if event.event_type not in self.EVIDENCE_TYPES:
                missing.append(ref)
                continue
            requested = ref if ref in event.source_refs else None
            for row in self.originals(event,requested):
                key = row.get("raw_ref") or row["event_id"]
                if key not in keys:
                    keys.add(key)
                    rows.append(row)
        page = self._page(rows, offset=offset, limit=limit, max_chars=max_chars, text_offset=text_offset)
        return {"reference":reference,"statement_id":statement_id,
            "status":"not_found" if not rows else "partial" if missing or queue or page["next_offset"] is not None else "complete",
            "granularity":"statement" if statements else "batch" if unit or any(e and e.event_type==CognitiveEventType.SOCIAL_SNAPSHOT for e in first) else "message",
            "statements":[{"statement_id":s.get("statement_id"),"evidence_count":len(s.get("raw_refs",[]))+len(s.get("source_event_ids",[]))} for s in statements],"total_records":len(rows), **page,
            "missing_refs":list(dict.fromkeys(missing))[:20],"missing_ref_count":len(set(missing)),"expansion_truncated":bool(queue),
            "notice":"未找到原消息，请使用有效的 SocialTrace 引用；不支持会话 ID。" if not rows else "摘要是概括，records 才是原消息；缺失或旧合并信息不得补猜。"}

    @staticmethod
    def _page(rows, *, offset=0, limit=8, max_chars=6000, text_offset=0):
        records, used = [], 0
        next_offset, next_text = None, None
        for index in range(offset,min(len(rows),offset+limit)):
            row = rows[index]
            start = text_offset if index==offset else 0
            room = max_chars-used
            if room<=0:
                next_offset,next_text = index,0
                break
            text = SocialTraceReader.original_text(row["content"],row["raw_message"])
            value = text[start:start+room]
            parts = [p for p in row["parts"] if p.get("type")=="image"]
            records.append({key:value for key,value in row.items() if key not in {"content","parts","raw_message"}} | {
                "content":value,"text_offset":start,"text_length":len(text),"truncated":start+len(value)<len(text),
                "image_count":len(parts),"image_status":"cached" if any(str(p.get("url") or p.get("file") or "").startswith("data:image/") for p in parts) else "unavailable" if parts else "none",
                "raw_payload_available":bool(row["raw_message"]),
                "segment_types":list(dict.fromkeys(p.get("type") for p in ((row["raw_message"] or {}).get("message") or []) if isinstance(p,dict))),
                "untrusted_external_data":True})
            used += len(value)
            if start+len(value)<len(text):
                next_offset,next_text = index,start+len(value)
                break
        if next_offset is None and offset+len(records)<len(rows):
            next_offset,next_text = offset+len(records),0
        return {"records": records, "next_offset": next_offset, "next_text_offset": next_text}

    def search(self, *, query=None, group_id=None, source_plugin=None, since=None, until=None,
               offset=0, limit=8, max_chars=6000, text_offset=0, turn=None):
        # Derive external scope from the authenticated turn, never from model arguments.
        local = turn is None or turn.output_channel == "desktop"
        if turn is not None:
            origin = from_event(turn.trigger_event)
            local = local or (turn.output_channel in {"web", "cli", "voice"} and turn.audience == "owner"
                              and origin.channel == turn.output_channel and origin.actor_role == "OWNER")
        if not local:
            if (origin.channel != "qq" or origin.conversation_kind != "group" or not origin.session_id
                or not origin.conversation_id or not origin.source_plugin
                or (group_id is not None and group_id != origin.conversation_id)
                or (source_plugin is not None and source_plugin != origin.source_plugin)):
                return {"status": "forbidden", "records": []}
            group_id, source_plugin = origin.conversation_id, origin.source_plugin
        hits = self.history.search(query=query, group_id=group_id, source_plugin=source_plugin,
                                   since=since, until=until, offset=offset, limit=limit)
        rows, missing = [], []
        for reference, event_id, total in hits:
            event = self.find(event_id)
            if event is None:
                missing.append(reference)
                continue
            if not social_access(event, turn):
                return {"status": "forbidden", "records": []}
            requested = reference if reference in event.source_refs else None
            originals = self.originals(event, requested)
            for row in originals:
                row["reference"] = reference
                if query:
                    row["match_text_offset"] = self.original_text(row["content"], row["raw_message"]).lower().find(query.lower())
                row["evidence_store"] = event.metadata.get("evidence_store", "experience")
            rows.extend(originals)
        page = self._page(rows, limit=limit, max_chars=max_chars, text_offset=text_offset)
        total = hits[0][2] if hits else 0
        if page["next_offset"] is not None:
            page["next_offset"] += offset
        elif offset + len(hits) < total:
            page["next_offset"], page["next_text_offset"] = offset + len(hits), 0
        return {"mode": "search", "query": query, "group_id": group_id, "source_plugin": source_plugin,
                "since": since.isoformat() if since else None, "until": until.isoformat() if until else None,
                "status": "not_found" if not hits else "partial" if missing or page["next_offset"] is not None else "complete",
                "total_records": total, "missing_refs": missing, **page,
                "notice": "搜索的是已保存的 QQ 群原消息；按发生时间从新到旧排列。没有命中不代表群内从未发生；旧正文与缺失载荷不补猜。"}

    def image_messages(self, result, cache, turn=None):
        from zhaoxi.core.message import Message,Role
        from .provenance import Provenance,render_for_context
        messages=[]
        for record in result.get("records",[]):
            event=self.find(record["event_id"])
            if event is None or not social_access(event,turn):
                continue
            row=next((r for r in self.originals(event,record.get("raw_ref")) if r.get("raw_ref")==record.get("raw_ref")),None)
            if row is None:
                continue
            images=[p.get("url") or p.get("file") for p in row["parts"] if p.get("type")=="image" and str(p.get("url") or p.get("file") or "").startswith("data:image/")]
            previews=[v for i,src in enumerate(images[:2]) if (v:=cache.thumbnail(record.get("raw_ref") or event.event_id,i,src))]
            if not previews:
                continue
            message=Message(role=Role.USER if row["provenance"].get("origin_actor_role")=="OWNER" else Role.EXTERNAL,message_id="social-image:"+(record.get("raw_ref") or event.event_id),
                content="回查的历史群聊图片，非本轮新图。",images=previews,source=event.source,
                metadata={**row["provenance"],"origin_event_id":None,"timeline_scope":"attention",
                    "image_timeline_scope":"attention","image_origin_event_id":record.get("raw_ref") or event.event_id})
            current=from_event(turn.trigger_event) if turn else Provenance(channel="desktop",session_id="local")
            messages.append(render_for_context(message,current))
            if len(messages)>=2:
                break
        return messages
