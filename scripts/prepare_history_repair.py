"""Prepare a reviewable, source-backed local history repair; apply only an approved manifest."""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(session, rows):
    return hashlib.sha256(encode([session, rows]).encode()).hexdigest()


def prepare(session_db, experience_db, session_id):
    from zhaoxi.core.message import Message, Role, clean_image_input_text
    with sqlite3.connect(Path(session_db).resolve().as_uri() + "?mode=ro", uri=True) as db:
        session = db.execute("SELECT created_at,updated_at,messages_json FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if session is None:
            raise ValueError("Session not found")
        rows = db.execute("SELECT sequence,message_id,message_json FROM session_history WHERE session_id=? ORDER BY sequence", (session_id,)).fetchall()
    history = [json.loads(row[2]) for row in rows]
    current = json.loads(session[2])
    groups = defaultdict(list)
    for index, message in enumerate(history):
        if message.get("delivery_id"):
            groups[message["delivery_id"]].append(index)
    deleted, conflicts = set(), []
    for delivery, indexes in groups.items():
        signatures = {encode({k: v for k, v in history[i].items() if k != "message_id"}) for i in indexes}
        if len(signatures) == 1:
            deleted.update(indexes[1:])
        else:
            conflicts.append({"delivery_id": delivery, "rows": len(indexes)})
    kept = [message for i, message in enumerate(history) if i not in deleted]
    users = [message for message in [*history, *current] if message["role"] == "user"]
    ids = {message["message_id"] for message in [*history, *current]}
    event_ids = {message.get("metadata", {}).get("event_id") for message in users}
    with sqlite3.connect(Path(experience_db).resolve().as_uri() + "?mode=ro", uri=True) as db:
        events = [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM events WHERE source IN ('desktop','web') AND actor_role='OWNER' "
            "AND event_type='USER_MESSAGE' AND session_id=? ORDER BY occurred_at", (session_id,))]
    start, end = datetime.fromisoformat(session[0]), datetime.fromisoformat(session[1])
    events = [event for event in events if start <= datetime.fromisoformat(event["occurred_at"]) <= end]
    missing = []
    for event in events:
        source_ids = [ref.partition(":")[2] for ref in event["source_refs"] if ref.startswith(("desktop:", "web:"))]
        if event["event_id"] in event_ids or any(identity in ids for identity in source_ids):
            continue
        event["_message_id"] = source_ids[0] if len(source_ids) == 1 else "recovered:" + event["event_id"]
        event["_images"] = [part.get("url") or part.get("file") for part in event["parts"]
                            if part["type"] == "image" and (part.get("url") or part.get("file"))]
        event["_text"] = clean_image_input_text(event.get("content"), has_images=bool(event["_images"]),
                                               input_text_present=event["metadata"].get("input_text_present")) or ""
        missing.append(event)
    legacy = {message["message_id"]: message for message in users if not message.get("metadata", {}).get("event_id")}
    matches = {}
    for event in missing:
        matches[event["event_id"]] = [identity for identity, message in legacy.items()
            if abs((datetime.fromisoformat(message["timestamp"]) - datetime.fromisoformat(event["occurred_at"])).total_seconds()) <= 120
            and (clean_image_input_text(message.get("content"), has_images=bool(message.get("images")),
                                        input_text_present=message.get("input_text_present")) or "") == event["_text"]
            and message.get("images", []) == event["_images"]]
    reverse = defaultdict(list)
    for event_id, identities in matches.items():
        for identity in identities:
            reverse[identity].append(event_id)
    additions, uncertain, already_present = [], [], []
    for event in missing:
        candidates = matches[event["event_id"]]
        if len(candidates) == 1 and len(reverse[candidates[0]]) == 1:
            already_present.append(event["event_id"])
            continue
        if candidates:
            uncertain.append({"event_id": event["event_id"], "possible_message_ids": candidates})
            continue
        value = Message(role=Role.USER, message_id=event["_message_id"], content=event["_text"],
                        timestamp=event["occurred_at"], source=event["source"],
                        input_text_present=event["metadata"].get("input_text_present"),
                        metadata={"event_id": event["event_id"], "recovered_from": "experience"}).model_dump(mode="json")
        value["images"] = event["_images"]  # Retain serialized media references without rewriting originals.
        additions.append(value)
    repaired = sorted([*kept, *additions], key=lambda message: datetime.fromisoformat(message["timestamp"]))
    return {"version": 1, "session_id": session_id, "fingerprint": fingerprint([session[0], session[2]], rows),
        "existing_rows": len(history), "duplicate_rows": len(deleted), "delivery_conflicts": conflicts,
        "source_events_in_current_session": len(events), "legacy_matches": already_present,
        "uncertain_matches": uncertain, "recovered_users": len(additions), "result_rows": len(repaired),
        "new_messages": additions, "messages": repaired, "approved": False}


def apply(session_db, manifest, backup_path):
    if not manifest.get("approved"):
        raise ValueError("The concrete migration manifest must be approved before applying")
    path = Path(session_db).resolve()
    backup = Path(backup_path).resolve()
    if backup == path or backup.exists():
        raise ValueError("Use a new backup path distinct from the database")
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        session = db.execute("SELECT created_at,messages_json FROM sessions WHERE session_id=?", (manifest["session_id"],)).fetchone()
        rows = db.execute("SELECT sequence,message_id,message_json FROM session_history WHERE session_id=? ORDER BY sequence", (manifest["session_id"],)).fetchall()
        if session is None or fingerprint(list(session), rows) != manifest["fingerprint"]:
            raise ValueError("Production history changed since preparation; prepare a fresh manifest")
        # The write lock prevents the source changing between backup and migration.
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        db.execute("DELETE FROM session_history WHERE session_id=?", (manifest["session_id"],))
        db.executemany("INSERT INTO session_history(session_id,message_id,message_json) VALUES (?,?,?)",
                       [(manifest["session_id"], message["message_id"], encode(message)) for message in manifest["messages"]])
        # Current model/session windows and other sessions remain untouched.
    return {"history_rows": manifest["result_rows"], "backup": str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-db", default=".zhaoxi/session.db")
    parser.add_argument("--experience-db", default=".zhaoxi/experience.db")
    parser.add_argument("--session-id", default="local")
    parser.add_argument("--output", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    args = parser.parse_args()
    output = Path(args.output)
    if args.apply:
        if not args.backup:
            parser.error("--backup is required with --apply")
        result = apply(args.session_db, json.loads(output.read_text(encoding="utf-8")), args.backup)
    else:
        result = prepare(args.session_db, args.experience_db, args.session_id)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    print(json.dumps({key: value for key, value in result.items() if key not in {"messages", "new_messages", "legacy_matches"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
