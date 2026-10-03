"""Owner operations, atomic revision log and targeted undo."""
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from .models import CognitionThread, JournalItem, ManualMetadata

COLLECTIONS = {"thread":"threads", "change":"recent_changes", "watch":"watch_items"}
class ManualEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    key: str | None = Field(default=None, min_length=1, max_length=60)
    title: str | None = Field(default=None, min_length=1, max_length=40)
    summary: str | None = Field(default=None, min_length=1, max_length=160)
    text: str | None = Field(default=None, min_length=1, max_length=160)
    manual_state: str | None = None
    merge_keys: list[str] = Field(default_factory=list, max_length=20)
    restore_auto: bool = False
    expected_version: int | None = None

def fingerprint(text):
    import re
    return re.sub(r"[^\w]", "", text.casefold())

def suppressed(state, key, text, refs, now, target_type="thread"):
    evidence = {r.event_id or r.message_id for r in refs if r.event_id or r.message_id}
    for record in state.manual_suppressions:
        if record.get("target_type", "thread") != target_type:
            continue
        if record.get("until") and now >= datetime.fromisoformat(record["until"]):
            continue
        equivalent = key == record["key"] or SequenceMatcher(None, fingerprint(text), record["fingerprint"]).ratio() >= .7
        old = set(record["source_evidence_refs"])
        if equivalent and (not evidence or not old or evidence <= old):
            return True
    return False

class CognitionEditor:
    def __init__(self, service):
        self.service = service

    def edit(self, target_type, key, edit, operation="edit"):
        from .service import normalize_key
        now = datetime.now(self.service.timezone)
        state = self.service.state()
        if edit.expected_version is not None and edit.expected_version != state.version:
            raise ValueError("近期认知已更新，请刷新后再保存")
        before = state.model_dump(mode="json")
        if target_type == "overview":
            if edit.restore_auto:
                state.overview_manual = ManualMetadata()
            else:
                state.overview = (edit.text if edit.text is not None else state.overview).strip()
                state.overview_manual = ManualMetadata(source="OWNER_MANUAL", manual_state="LOCKED", updated_by="owner", manual_updated_at=now, manual_revision=state.overview_manual.manual_revision+1)
        else:
            collection = getattr(state, COLLECTIONS[target_type])
            item = next((x for x in collection if x.key == key), None)
            if operation == "add":
                key = normalize_key(edit.key or uuid4().hex)
                if not key or any(x.key == key for x in collection):
                    raise ValueError("条目 key 重复或无效")
                if len(collection) >= 50:
                    raise ValueError("近期认知最多保留 50 个同类条目")
                if target_type == "thread":
                    if not (edit.title or "").strip() or not (edit.summary or "").strip():
                        raise ValueError("主线需要标题与正文")
                    item = CognitionThread(key=key,title=edit.title.strip(),summary=edit.summary.strip(),first_seen_at=now,last_updated_at=now,last_evidence_at=now)
                else:
                    if not (edit.text or "").strip():
                        raise ValueError("条目正文不能为空")
                    item = JournalItem(key=key,text=edit.text.strip(),created_at=now,updated_at=now)
                collection.append(item)
            if item is None:
                raise KeyError(key)
            if edit.title is not None and target_type == "thread": item.title = edit.title.strip()
            if edit.summary is not None and target_type == "thread": item.summary = edit.summary.strip()
            if edit.text is not None and target_type != "thread":
                item.text = JournalItem.model_validate({**item.model_dump(),"text":edit.text.strip()}).text
            if edit.manual_state:
                if edit.manual_state not in {"NORMAL","PINNED","LOCKED","RESOLVED","DISMISSED"}:
                    raise ValueError("无效人工状态")
                item.manual_state = edit.manual_state
            if operation == "fade" and target_type == "thread":
                item.status = "cooling"
                item.salience = min(item.salience,.45)
            if operation == "delete": item.manual_state = "DISMISSED"
            if edit.merge_keys:
                if target_type != "thread": raise ValueError("只允许合并主线")
                for other_key in edit.merge_keys:
                    if other_key == key: continue
                    other = next((x for x in collection if x.key == other_key), None)
                    if other is None: raise KeyError(other_key)
                    item.source_refs = (item.source_refs+other.source_refs)[-8:]
                    self._suppress(state, other, target_type, now)
                    collection.remove(other)
            item.source, item.updated_by, item.manual_updated_at = "OWNER_MANUAL", "owner", now
            item.manual_revision += 1
            if target_type == "thread": item.last_updated_at = now
            else: item.updated_at = now
            if item.manual_state in {"RESOLVED","DISMISSED"}:
                self._suppress(state, item, target_type, now)
                collection.remove(item)
        state.version += 1
        state.updated_at = now
        state = type(state).model_validate(state.model_dump())
        revision_id = self.service.store.save_manual(state,target_type=target_type,target_id=key or "overview",operation=operation,before=before)
        return {"state":state.model_dump(mode="json"),"revision_id":revision_id}

    def _suppress(self, state, item, target_type, now):
        state.manual_suppressions = [r for r in state.manual_suppressions if not (r["key"] == item.key and r.get("target_type","thread") == target_type)]
        state.manual_suppressions.append({"key":item.key,"target_type":target_type,
            "fingerprint":fingerprint((item.title+item.summary) if target_type=="thread" else item.text),
            "source_evidence_refs":[r.event_id or r.message_id for r in item.source_refs],
            "until":(now+timedelta(days=7)).isoformat(),"manual_state":item.manual_state})

    def undo(self, revision_id=None):
        revisions = self.service.store.revisions(limit=1)["items"]
        if not revisions or revisions[0]["undone"] or revision_id is not None and revisions[0]["revision_id"] != revision_id:
            raise ValueError("只能撤销最近一次尚未撤销的人工修改")
        record = revisions[0]
        state = self.service.state()
        before, after = record["before"],record["after"]
        if record["target_type"] == "overview":
            if state.overview != after["overview"] or state.overview_manual.model_dump(mode="json") != after["overview_manual"]:
                raise ValueError("目标在修改后已有新变化，请人工核对")
            state.overview, state.overview_manual = before["overview"],ManualMetadata.model_validate(before["overview_manual"])
        else:
            attr = COLLECTIONS[record["target_type"]]
            old = {x["key"]:x for x in before[attr]}
            new = {x["key"]:x for x in after[attr]}
            affected = {k for k in old.keys()|new.keys() if old.get(k)!=new.get(k)}
            current = {x.key:x.model_dump(mode="json") for x in getattr(state,attr)}
            if any(current.get(k)!=new.get(k) for k in affected):
                raise ValueError("目标在修改后已有新变化，请人工核对")
            cls = CognitionThread if record["target_type"]=="thread" else JournalItem
            setattr(state,attr,[x for x in getattr(state,attr) if x.key not in affected]+[cls.model_validate(old[k]) for k in affected if k in old])
        # Revert only suppressions created by this operation; retain unrelated runtime work.
        added = [x for x in after["manual_suppressions"] if x not in before["manual_suppressions"]]
        state.manual_suppressions = [x for x in state.manual_suppressions if x not in added]
        state.manual_suppressions += [x for x in before["manual_suppressions"] if x not in after["manual_suppressions"] and x not in state.manual_suppressions]
        state.version += 1
        state.updated_at = datetime.now(self.service.timezone)
        self.service.store.save_undo(state,record["revision_id"])
        return state.model_dump(mode="json")
