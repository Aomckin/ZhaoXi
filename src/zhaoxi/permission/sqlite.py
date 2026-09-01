"""SQLite-backed permission confirmations and one-use grants."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from zhaoxi.permission.models import PendingConfirmation, PermissionGrant
from zhaoxi.permission.store import InMemoryPermissionStore


SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS permission_pending (
    confirmation_id TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    resolved INTEGER NOT NULL,
    item_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permission_grants (
    grant_id TEXT PRIMARY KEY,
    confirmation_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL,
    item_json TEXT NOT NULL
);
"""


class SQLitePermissionStore(InMemoryPermissionStore):
    """Keep the existing synchronous contract and persist every mutation atomically."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        super().__init__()
        self._load()

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
                raise RuntimeError("Permission 数据库版本高于当前程序支持版本。")

    def _load(self) -> None:
        with self._connect() as connection:
            pending = connection.execute("SELECT item_json FROM permission_pending").fetchall()
            grants = connection.execute("SELECT item_json FROM permission_grants").fetchall()
        self.pending = {
            item.confirmation_id: item
            for item in (PendingConfirmation.model_validate_json(row["item_json"]) for row in pending)
        }
        self.grants = {
            item.grant_id: item
            for item in (PermissionGrant.model_validate_json(row["item_json"]) for row in grants)
        }

    def save_pending(self, item: PendingConfirmation) -> PendingConfirmation:
        result = super().save_pending(item)
        self._persist_pending(result)
        return result

    def approve(self, confirmation_id: str) -> PermissionGrant:
        grant = super().approve(confirmation_id)
        self._persist_pending(self.pending[confirmation_id])
        self._persist_grant(grant)
        return grant

    def deny(self, confirmation_id: str) -> PendingConfirmation:
        item = super().deny(confirmation_id)
        self._persist_pending(item)
        return item

    def consume_matching(self, request):
        grant = super().consume_matching(request)
        if grant is not None:
            self._persist_grant(grant)
        return grant

    def revoke(self, grant_id: str) -> PermissionGrant:
        grant = super().revoke(grant_id)
        self._persist_grant(grant)
        return grant

    def save_grant(self, grant: PermissionGrant) -> PermissionGrant:
        self.grants[grant.grant_id] = grant
        self._persist_grant(grant)
        return grant

    def _persist_pending(self, item: PendingConfirmation) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO permission_pending VALUES (?, ?, ?, ?)
                ON CONFLICT(confirmation_id) DO UPDATE SET expires_at=excluded.expires_at,
                resolved=excluded.resolved, item_json=excluded.item_json""",
                (item.confirmation_id, item.expires_at.isoformat(), item.resolved, item.model_dump_json()),
            )

    def _persist_grant(self, item: PermissionGrant) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO permission_grants VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(grant_id) DO UPDATE SET expires_at=excluded.expires_at,
                revoked=excluded.revoked, item_json=excluded.item_json""",
                (
                    item.grant_id,
                    item.confirmation_id,
                    item.expires_at.isoformat(),
                    item.revoked,
                    item.model_dump_json(),
                ),
            )
