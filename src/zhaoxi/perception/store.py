"""SQLite inbox with transactional deduplication and recoverable ambient buckets."""
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zhaoxi.perception.models import Observation, ObservationBatch, ObservationStatus, SocialSnapshot


class PerceptionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, raw_ref TEXT,
                    bucket TEXT NOT NULL, status TEXT NOT NULL,
                    occurred_at TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS observations_source_ref
                    ON observations(source, raw_ref) WHERE raw_ref IS NOT NULL;
                CREATE INDEX IF NOT EXISTS observations_buffered ON observations(status, bucket, received_at);
                CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    window_end TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshot_cognition (
                    snapshot_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'PENDING');
            """)

    def fail_inflight(self) -> None:
        """Mark direct calls interrupted by a previous process as failed at startup."""
        with self._connect() as db:
            db.execute("UPDATE observations SET status=? WHERE status=?", (
                ObservationStatus.FAILED.value, ObservationStatus.PENDING.value))

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def bucket(item: Observation) -> str:
        return f"{item.source}:{item.conversation_kind or ''}:{item.conversation_id or ''}"

    def insert(self, item: Observation, status: ObservationStatus) -> bool:
        with self._connect() as db:
            cursor = db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?)", (
                item.observation_id, item.source, item.raw_ref, self.bucket(item), status.value,
                item.occurred_at.isoformat(), item.received_at.isoformat(), item.model_dump_json()))
            return cursor.rowcount == 1

    def buffered(self, bucket: str | None = None, *, limit: int = 1000) -> list[Observation]:
        with self._connect() as db:
            if bucket is None:
                rows = db.execute("SELECT payload FROM observations WHERE status=? ORDER BY received_at LIMIT ?",
                                  (ObservationStatus.BUFFERED.value, limit)).fetchall()
            else:
                rows = db.execute("SELECT payload FROM observations WHERE status=? AND bucket=? ORDER BY received_at LIMIT ?",
                                  (ObservationStatus.BUFFERED.value, bucket, limit)).fetchall()
        return [Observation.model_validate_json(row[0]) for row in rows]

    def buckets(self) -> list[str]:
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT DISTINCT bucket FROM observations WHERE status=?",
                                                  (ObservationStatus.BUFFERED.value,))]

    def commit_batch(self, batch: ObservationBatch, snapshot: SocialSnapshot) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO batches VALUES (?,?)", (batch.batch_id, batch.model_dump_json()))
            db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)", (
                snapshot.snapshot_id, snapshot.source, snapshot.conversation_id,
                snapshot.window_end.isoformat(), snapshot.model_dump_json()))
            db.execute("INSERT INTO snapshot_cognition(snapshot_id,status) VALUES (?,?)",
                       (snapshot.snapshot_id, "PENDING"))
            db.executemany("UPDATE observations SET status=? WHERE id=? AND status=?", (
                (ObservationStatus.PROCESSED.value, item_id, ObservationStatus.BUFFERED.value)
                for item_id in batch.observation_ids))

    def recent_snapshots(self, source: str, conversation_id: str, *, limit: int = 3,
                         since: datetime | None = None) -> list[SocialSnapshot]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM snapshots WHERE source=? AND conversation_id=? AND window_end>=? ORDER BY window_end DESC LIMIT ?",
                              (source, conversation_id, (since or datetime.min.replace(tzinfo=UTC)).isoformat(), limit)).fetchall()
        return [SocialSnapshot.model_validate_json(row[0]) for row in rows]

    def clear_expired(self, ttl_hours: int, now: datetime | None = None) -> int:
        threshold = ((now or datetime.now(UTC)) - timedelta(hours=ttl_hours)).isoformat()
        with self._connect() as db:
            cursor = db.execute("DELETE FROM observations WHERE received_at < ?", (threshold,))
            db.execute("DELETE FROM snapshots WHERE window_end < ?", (threshold,))
            db.execute("DELETE FROM snapshot_cognition WHERE snapshot_id NOT IN (SELECT id FROM snapshots)")
            stale_batches = [row[0] for row in db.execute("SELECT id, payload FROM batches")
                if ObservationBatch.model_validate_json(row[1]).window_end.astimezone(UTC).isoformat() < threshold]
            db.executemany("DELETE FROM batches WHERE id=?", ((item,) for item in stale_batches))
            return cursor.rowcount

    def set_status(self, observation_id: str, status: ObservationStatus) -> None:
        with self._connect() as db:
            db.execute("UPDATE observations SET status=? WHERE id=?", (status.value, observation_id))

    def recent_observations(self, limit: int = 20) -> list[Observation]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM observations ORDER BY received_at DESC LIMIT ?", (limit,)).fetchall()
        return [Observation.model_validate_json(row[0]) for row in rows]

    def recent_all_snapshots(self, limit: int = 10) -> list[SocialSnapshot]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM snapshots ORDER BY window_end DESC LIMIT ?", (limit,)).fetchall()
        return [SocialSnapshot.model_validate_json(row[0]) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as db:
            return {row[0]: row[1] for row in db.execute("SELECT status, COUNT(*) FROM observations GROUP BY status")}

    def pending_snapshots(self, limit: int = 5) -> list[SocialSnapshot]:
        with self._connect() as db:
            rows = db.execute("""SELECT s.payload FROM snapshots s
                JOIN snapshot_cognition c ON c.snapshot_id=s.id
                WHERE c.status='PENDING' ORDER BY s.window_end LIMIT ?""", (limit,)).fetchall()
        return [SocialSnapshot.model_validate_json(row[0]) for row in rows]

    def set_snapshot_cognition(self, snapshot_id: str, status: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE snapshot_cognition SET status=? WHERE snapshot_id=?",
                       (status, snapshot_id))
