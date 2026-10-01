"""Durable named phases, bounded batching and Owner-priority scheduling.

Interrupted writes remain uncertain and are never automatically replayed.
"""
from __future__ import annotations
import asyncio
import json
import sqlite3
from pathlib import Path
from time import monotonic, time
from zhaoxi.reliability.lifecycle import TaskSupervisor

DEFAULT_PHASES = ("auto_memory", "current_cognition")


class PostTurnMaintenanceQueue:
    def __init__(self, path, handler, *, foreground_busy=lambda: False, publish=lambda event: None,
                 limit=100, phases=DEFAULT_PHASES, batch_delay=.5):
        if not phases or len(set(phases)) != len(phases) or any(not isinstance(p,str) or not p for p in phases):
            raise ValueError("phases must be unique nonempty names")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE IF NOT EXISTS maintenance (id TEXT PRIMARY KEY, payload TEXT NOT NULL, phase INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT, duration_ms REAL NOT NULL DEFAULT 0)")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(maintenance)")}
        for name, declaration in {"metrics":"TEXT NOT NULL DEFAULT '{}'", "attempts":"INTEGER NOT NULL DEFAULT 0",
                "phases":"TEXT NOT NULL DEFAULT '[]'", "priority":"INTEGER NOT NULL DEFAULT 0",
                "batch_key":"TEXT", "ready_at":"REAL NOT NULL DEFAULT 0"}.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE maintenance ADD COLUMN {name} {declaration}")
        # Translate legacy cursor exactly once. A persisted plan never changes
        # when a later release adds, removes or reorders its configured phases.
        for row in self.db.execute("SELECT id,phase,metrics FROM maintenance WHERE phases='[]'").fetchall():
            metrics = json.loads(row['metrics'])
            for name in DEFAULT_PHASES[:row['phase']]:
                metrics.setdefault(name, {"status":"completed", "legacy_checkpoint":True})
            self.db.execute("UPDATE maintenance SET phases=?,metrics=? WHERE id=?",
                (json.dumps(DEFAULT_PHASES),json.dumps(metrics),row['id']))
        self.db.execute("UPDATE maintenance SET status='uncertain',error='interrupted_process' WHERE status='running'")
        self.db.commit()
        self.handler, self.foreground_busy, self.publish, self.limit = handler, foreground_busy, publish, limit
        self.phases, self.batch_delay = tuple(phases), batch_delay
        self.supervisor, self.worker = TaskSupervisor(), None

    def enqueue(self, key, payload, *, priority=0, batch_key=None, batch_limit=8):
        if self.db.execute("SELECT 1 FROM maintenance WHERE id=?", (key,)).fetchone():
            return
        payload = json.loads(json.dumps(payload, ensure_ascii=False))
        if batch_key:
            row = self.db.execute("SELECT * FROM maintenance WHERE status='queued' AND attempts=0 AND batch_key=? ORDER BY rowid DESC LIMIT 1",(batch_key,)).fetchone()
            if row:
                existing = json.loads(row['payload'])
                triggers = existing.get('triggers') or ([existing['trigger']] if existing.get('trigger') else [])
                additions = payload.get('triggers') or ([payload['trigger']] if payload.get('trigger') else [])
                unique = {event['event_id']:event for event in [*triggers,*additions]}
                if len(unique) <= batch_limit:
                    existing.update(triggers=list(unique.values()), reply=payload.get('reply',''))
                    messages = {m['message_id']:m for m in [*existing.get('messages',[]),*payload.get('messages',[])]}
                    existing['messages'] = list(messages.values())[-200:]
                    self.db.execute("UPDATE maintenance SET payload=?,priority=MAX(priority,?) WHERE id=?",
                        (json.dumps(existing,ensure_ascii=False),priority,row['id']))
                    self.db.execute("INSERT INTO maintenance(id,payload,status,phases,metrics) VALUES(?,?,'coalesced',?,?)",
                        (key,'{}',json.dumps(self.phases),json.dumps({'batch_parent':row['id']})))
                    self.db.commit()
                    self.publish({"type":"maintenance_status","request_id":key,"status":"coalesced","batch_parent":row['id']})
                    self.start()
                    return
        pending = self.db.execute("SELECT count(*) FROM maintenance WHERE status IN ('queued','running')").fetchone()[0]
        status = "rejected" if pending >= self.limit else "queued"
        self.db.execute("INSERT INTO maintenance(id,payload,status,error,phases,priority,batch_key,ready_at) VALUES(?,?,?,?,?,?,?,?)",
            (key,json.dumps(payload,ensure_ascii=False),status,"queue_full" if status=='rejected' else None,
             json.dumps(self.phases),priority,batch_key,time()+self.batch_delay if batch_key else 0))
        self.db.commit()
        self.publish({"type":"maintenance_status","request_id":key,"status":status})
        self.start()

    def start(self):
        if self.supervisor.accepting and (self.worker is None or self.worker.done()):
            self.worker = self.supervisor.create(self.run(), name="post-turn-maintenance")

    async def run(self):
        while True:
            await asyncio.sleep(.05)
            if self.foreground_busy():
                if not self.db.execute("SELECT 1 FROM maintenance WHERE status='queued'").fetchone():
                    return
                continue
            row = self.db.execute("SELECT * FROM maintenance WHERE status='queued' AND ready_at<=? ORDER BY priority DESC,rowid LIMIT 1",(time(),)).fetchone()
            if row is None:
                if self.db.execute("SELECT 1 FROM maintenance WHERE status='queued'").fetchone():
                    continue
                return
            key, payload, phases = row['id'],json.loads(row['payload']),json.loads(row['phases'])
            self.db.execute("UPDATE maintenance SET status='running',attempts=attempts+1 WHERE id=?",(key,))
            self.db.commit()
            started = monotonic()
            try:
                for name in phases:
                    recorded = json.loads(self.db.execute("SELECT metrics FROM maintenance WHERE id=?",(key,)).fetchone()[0])
                    if name in recorded:
                        continue
                    phase_started = monotonic()
                    try:
                        metrics = await self.handler(payload, name)
                        result = {"status":"completed","error":None,"metrics":metrics}
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        result = {"status":"failed","error":type(exc).__name__,"metrics":{}}
                    result['duration_ms'] = (monotonic()-phase_started)*1000
                    recorded[name] = result
                    self.db.execute("UPDATE maintenance SET metrics=?,phase=? WHERE id=?",(json.dumps(recorded),len(recorded),key))
                    self.db.commit()
                    if self.foreground_busy() and any(p not in recorded for p in phases):
                        self.db.execute("UPDATE maintenance SET status='queued' WHERE id=?",(key,))
                        break
                else:
                    failures = [name for name in phases if recorded[name]['status']=='failed']
                    self.db.execute("UPDATE maintenance SET status=?,error=? WHERE id=?",
                        ('failed' if len(failures)==len(phases) else 'partial_failed' if failures else 'completed',','.join(failures) or None,key))
            except asyncio.CancelledError:
                self.db.execute("UPDATE maintenance SET status='uncertain',error='cancelled_running' WHERE id=? AND status='running'",(key,))
                raise
            except Exception as exc:
                self.db.execute("UPDATE maintenance SET status='failed',error=? WHERE id=?",(type(exc).__name__,key))
            finally:
                self.db.execute("UPDATE maintenance SET duration_ms=duration_ms+? WHERE id=?",((monotonic()-started)*1000,key))
                self.db.commit()
                state = self.db.execute("SELECT status,error,duration_ms FROM maintenance WHERE id=?",(key,)).fetchone()
                self.publish({"type":"maintenance_status","request_id":key,**dict(state)})
                self.db.execute("UPDATE maintenance SET payload='{}' WHERE status NOT IN ('queued','running') AND rowid NOT IN (SELECT rowid FROM maintenance ORDER BY rowid DESC LIMIT 200)")
                self.db.commit()

    def invalidate(self):
        self.db.execute("UPDATE maintenance SET status='cancelled',error='session_cleared' WHERE status IN ('queued','running')")
        self.db.commit()
        if self.worker and not self.worker.done():
            self.worker.cancel()

    def diagnostics(self):
        return [{**dict(row),"max_attempts":1,"retry_backoff_ms":0,"phases":json.loads(row['phases']),"metrics":json.loads(row['metrics'])}
            for row in self.db.execute("SELECT id,status,phase,phases,priority,batch_key,error,duration_ms,attempts,metrics FROM maintenance ORDER BY rowid DESC LIMIT 30")]

    async def shutdown(self, grace=2):
        return await self.supervisor.shutdown(grace)
