"""Persist first, then route; direct replies never enter the local conversation."""
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zhaoxi.perception.context import build_external_messages
from zhaoxi.perception.digest import digest, make_batch
from zhaoxi.perception.models import AttentionHint, Observation, ObservationStatus
from zhaoxi.perception.router import route
from zhaoxi.perception.store import PerceptionStore

logger = logging.getLogger("PERCEPTION")


class PerceptionRuntime:
    def __init__(self, settings, agent, store: PerceptionStore | None = None):
        self.settings = settings
        self.agent = agent
        self.store = store or PerceptionStore(settings.perception_db_path)
        self.store.fail_inflight()
        self.status = "ready"
        self.direct_count = 0
        self.ignored_count = 0
        self.last_observation = None
        self.last_batch = None
        self.last_snapshot = None
        self.last_error = None
        self.source = None
        self._lock = asyncio.Lock()

    async def ingest(self, item: Observation) -> str | None:
        decision = route(item)
        status = {AttentionHint.IGNORE: ObservationStatus.IGNORED,
                  AttentionHint.AMBIENT: ObservationStatus.BUFFERED,
                  AttentionHint.DIRECT: ObservationStatus.PENDING}[decision]
        if not self.store.insert(item, status):
            return None
        self.last_observation = item.received_at.isoformat()
        self.agent.metrics.increment("perception.observation.received")
        self.agent.metrics.increment("perception.observation." + decision.value.lower())
        if decision is AttentionHint.IGNORE:
            self.ignored_count += 1
            return None
        if decision is AttentionHint.AMBIENT:
            if len(self.store.buffered(self.store.bucket(item), limit=self.settings.perception_batch_max_messages)) >= self.settings.perception_batch_max_messages:
                await self.flush(self.store.bucket(item))
            return None
        self.direct_count += 1
        try:
            messages = build_external_messages(item, self.store, self.agent.context_builder.character_prompt,
                snapshot_limit=self.settings.perception_snapshot_limit,
                max_chars=self.settings.perception_context_max_chars)
            async with self.agent.conversation_lock:
                response = await asyncio.wait_for(self.agent.provider.generate(messages, []), timeout=60)
            content = (response.content or "").strip()
            if not content or response.tool_calls:
                raise ValueError("external response missing safe text")
            self.store.set_status(item.observation_id, ObservationStatus.PROCESSED)
            return content[:2000]
        except Exception as exc:
            self.store.set_status(item.observation_id, ObservationStatus.FAILED)
            self.last_error = type(exc).__name__
            logger.warning("direct failed type=%s", type(exc).__name__)
            return None

    async def flush(self, bucket: str | None = None, *, force: bool = False) -> int:
        made = 0
        async with self._lock:
            for key in ([bucket] if bucket else self.store.buckets()):
                items = self.store.buffered(key)
                if not items:
                    continue
                oldest = min(x.received_at for x in items)
                if not force and len(items) < self.settings.perception_batch_max_messages and (
                    datetime.now(UTC) - oldest).total_seconds() < self.settings.perception_batch_window_seconds:
                    continue
                batch = make_batch(items)
                try:
                    snapshot = await digest(batch, items, self.agent.provider)
                    self.store.commit_batch(batch, snapshot)
                    self.last_batch = batch.batch_id
                    self.last_snapshot = snapshot.snapshot_id
                    self.agent.metrics.increment("perception.batch.created")
                    self.agent.metrics.increment("perception.snapshot.created")
                    made += 1
                except Exception as exc:
                    self.last_error = type(exc).__name__
                    self.agent.metrics.increment("perception.snapshot.failed")
                    logger.warning("digest failed type=%s", type(exc).__name__)
        return made

    async def run(self):
        self.status = "running"
        try:
            while True:
                await asyncio.sleep(min(30, self.settings.perception_batch_window_seconds))
                await self.flush()
                self.store.clear_expired(self.settings.perception_observation_ttl_hours)
        finally:
            self.status = "stopped"

    def diagnostics(self):
        return {"enabled": True, "status": self.status, "source_count": 1 if self.source else 0,
                "pending_observation_count": self.store.counts().get("PENDING", 0),
                "buffered_conversation_count": len(self.store.buckets()),
                "last_observation": self.last_observation, "last_batch": self.last_batch,
                "last_snapshot": self.last_snapshot, "direct_event_count": self.direct_count,
                "ignored_event_count": self.ignored_count, "last_error": self.last_error,
                "qq": self.source.diagnostics() if self.source else {"connected": False}}
