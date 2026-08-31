"""SQLite persistence for workflow runs."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from zhaoxi.workflow.models import WorkflowRun
from zhaoxi.workflow.store import WorkflowStore


class SQLiteWorkflowStore(WorkflowStore):
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
            )
            row = connection.execute(
                "SELECT version FROM schema_version WHERE component='workflow'"
            ).fetchone()
            if row and row[0] > self.SCHEMA_VERSION:
                raise RuntimeError("Workflow 数据库版本高于当前程序支持版本。")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    workflow_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_runs_updated ON workflow_runs(updated_at DESC)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_version(component, version) VALUES('workflow', ?)",
                (self.SCHEMA_VERSION,),
            )

    async def save(self, run: WorkflowRun) -> None:
        await asyncio.to_thread(self._save_sync, run.model_copy(deep=True))

    def _save_sync(self, run: WorkflowRun) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO workflow_runs(id, workflow_id, workflow_version, status, created_at, updated_at, payload)
                   VALUES(?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     status=excluded.status, updated_at=excluded.updated_at, payload=excluded.payload""",
                (
                    run.id,
                    run.workflow_id,
                    run.workflow_version,
                    run.status.value,
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                    run.model_dump_json(),
                ),
            )

    async def get(self, run_id: str) -> WorkflowRun | None:
        return await asyncio.to_thread(self._get_sync, run_id)

    def _get_sync(self, run_id: str) -> WorkflowRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
        return WorkflowRun.model_validate_json(row[0]) if row else None

    async def list(self, limit: int = 100) -> list[WorkflowRun]:
        safe_limit = max(1, min(limit, 1000))
        return await asyncio.to_thread(self._list_sync, safe_limit)

    def _list_sync(self, limit: int) -> list[WorkflowRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM workflow_runs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [WorkflowRun.model_validate_json(row[0]) for row in rows]
