"""SQLite persistence for recoverable planner goals."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from zhaoxi.errors import PlannerTaskNotFoundError
from zhaoxi.planner.models import Goal
from zhaoxi.planner.store import PlanStore


SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS planner_goals (
    goal_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    goal_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_planner_goals_updated
ON planner_goals(updated_at DESC);
"""


class SQLitePlanStore(PlanStore):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] > SCHEMA_VERSION:
                raise RuntimeError("Planner 数据库版本高于当前程序支持版本。")

    async def save(self, goal: Goal) -> None:
        await asyncio.to_thread(self._save, goal)

    def _save(self, goal: Goal) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO planner_goals(goal_id, status, updated_at, goal_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(goal_id) DO UPDATE SET status=excluded.status,
                updated_at=excluded.updated_at, goal_json=excluded.goal_json""",
                (goal.id, goal.status.value, goal.updated_at.isoformat(), goal.model_dump_json()),
            )

    async def get(self, goal_id: str) -> Goal | None:
        return await asyncio.to_thread(self._get, goal_id)

    def _get(self, goal_id: str) -> Goal | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT goal_json FROM planner_goals WHERE goal_id=?", (goal_id,)
            ).fetchone()
        return Goal.model_validate_json(row["goal_json"]) if row else None

    async def require(self, goal_id: str) -> Goal:
        goal = await self.get(goal_id)
        if goal is None:
            raise PlannerTaskNotFoundError(f"没有找到任务 {goal_id}。")
        return goal

    async def list(self) -> list[Goal]:
        return await asyncio.to_thread(self._list)

    def _list(self) -> list[Goal]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT goal_json FROM planner_goals ORDER BY updated_at DESC"
            ).fetchall()
        return [Goal.model_validate_json(row["goal_json"]) for row in rows]
