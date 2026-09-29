"""Durable, bounded, single-consumer post-turn maintenance.

Interrupted running work is marked uncertain, never blindly replayed. Queued
snapshots survive restart; completed phases are checkpointed before the next one.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from time import monotonic

from zhaoxi.reliability.lifecycle import TaskSupervisor


class PostTurnMaintenanceQueue:
    def __init__(self, path, handler, *, foreground_busy=lambda: False, publish=lambda event: None, limit=100):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE IF NOT EXISTS maintenance (id TEXT PRIMARY KEY, payload TEXT NOT NULL, phase INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT, duration_ms REAL NOT NULL DEFAULT 0)")
        if "metrics" not in {row[1] for row in self.db.execute("PRAGMA table_info(maintenance)")}:
            self.db.execute("ALTER TABLE maintenance ADD COLUMN metrics TEXT NOT NULL DEFAULT '{}'")
        if "attempts" not in {row[1] for row in self.db.execute("PRAGMA table_info(maintenance)")}:
            self.db.execute("ALTER TABLE maintenance ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        self.db.execute("UPDATE maintenance SET status='uncertain',error='interrupted_process' WHERE status='running'")
        self.db.commit()
        self.handler, self.foreground_busy, self.publish, self.limit = handler, foreground_busy, publish, limit
        self.supervisor = TaskSupervisor()
        self.worker = None

    def enqueue(self, key, payload):
        if self.db.execute("SELECT 1 FROM maintenance WHERE id=?", (key,)).fetchone():
            return
        pending = self.db.execute("SELECT count(*) FROM maintenance WHERE status IN ('queued','running')").fetchone()[0]
        status = "rejected" if pending >= self.limit else "queued"
        # JSON encoding freezes the snapshot before any asynchronous execution.
        self.db.execute("INSERT INTO maintenance(id,payload,status,error) VALUES(?,?,?,?)",
                        (key, json.dumps(payload, ensure_ascii=False), status, "queue_full" if status == "rejected" else None))
        self.db.commit()
        self.publish({"type": "maintenance_status", "request_id": key, "status": status})
        self.start()

    def start(self):
        if self.supervisor.accepting and (self.worker is None or self.worker.done()):
            self.worker = self.supervisor.create(self.run(), name="post-turn-maintenance")

    async def run(self):
        while True:
            row = self.db.execute("SELECT * FROM maintenance WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                return
            # Let foreground requests enter before reserving a model call.
            await asyncio.sleep(0.05)
            if self.foreground_busy():
                continue
            key, payload, phase = row["id"], json.loads(row["payload"]), row["phase"]
            current = self.db.execute("SELECT status FROM maintenance WHERE id=?", (key,)).fetchone()
            if current[0] != "queued":
                continue
            # Automatic memory writes are not known to be replay-safe. The retry
            # ceiling is deliberately one attempt; interrupted work is uncertain
            # and operator-visible instead of being duplicated after restart.
            self.db.execute("UPDATE maintenance SET status='running',attempts=attempts+1 WHERE id=?", (key,))
            self.db.commit()
            started = monotonic()
            try:
                for index in range(phase, 2):
                    metrics = await self.handler(payload, index)
                    recorded = json.loads(self.db.execute("SELECT metrics FROM maintenance WHERE id=?", (key,)).fetchone()[0])
                    recorded[str(index)] = metrics
                    self.db.execute("UPDATE maintenance SET metrics=? WHERE id=?", (json.dumps(recorded), key))
                    self.db.execute("UPDATE maintenance SET phase=? WHERE id=?", (index + 1, key))
                    self.db.commit()
                    if index == 0 and self.foreground_busy():
                        self.db.execute("UPDATE maintenance SET status='queued' WHERE id=?", (key,))
                        break
                else:
                    self.db.execute("UPDATE maintenance SET status='completed' WHERE id=?", (key,))
            except asyncio.CancelledError:
                self.db.execute("UPDATE maintenance SET status='uncertain',error='cancelled_running' WHERE id=? AND status='running'", (key,))
                raise
            except Exception as exc:
                self.db.execute("UPDATE maintenance SET status='failed',error=? WHERE id=?", (type(exc).__name__, key))
            finally:
                self.db.execute("UPDATE maintenance SET duration_ms=duration_ms+? WHERE id=?", ((monotonic()-started)*1000, key))
                self.db.commit()
                state = self.db.execute("SELECT status,error,duration_ms FROM maintenance WHERE id=?", (key,)).fetchone()
                self.publish({"type": "maintenance_status", "request_id": key, **dict(state)})
                # Retain bounded diagnostics; pending snapshots are never pruned.
                self.db.execute("UPDATE maintenance SET payload='{}' WHERE status NOT IN ('queued','running') AND rowid NOT IN (SELECT rowid FROM maintenance ORDER BY rowid DESC LIMIT 200)")
                self.db.commit()

    def invalidate(self):
        self.db.execute("UPDATE maintenance SET status='cancelled',error='session_cleared' WHERE status IN ('queued','running')")
        self.db.commit()
        if self.worker and not self.worker.done():
            self.worker.cancel()

    def diagnostics(self):
        return [{**dict(row), "max_attempts": 1, "retry_backoff_ms": 0,
                 "metrics": json.loads(row["metrics"])}
                for row in self.db.execute("SELECT id,status,phase,error,duration_ms,attempts,metrics FROM maintenance ORDER BY rowid DESC LIMIT 30")]

    async def shutdown(self, grace=2):
        return await self.supervisor.shutdown(grace)
