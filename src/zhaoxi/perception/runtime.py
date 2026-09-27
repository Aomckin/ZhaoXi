"""Persist external observations and coordinate channel cognition."""
import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from pydantic import ValidationError

from zhaoxi.core.message import Message, Role
from zhaoxi.perception.context import build_external_messages, session_key
from zhaoxi.perception.digest import digest, make_batch
from zhaoxi.perception.images import ImageResolver
from zhaoxi.perception.ledger import InteractionLedger
from zhaoxi.perception.models import AttentionHint, Observation, ObservationStatus
from zhaoxi.perception.planner import ExternalCognitionPlanner
from zhaoxi.perception.router import route
from zhaoxi.perception.store import PerceptionStore

logger = logging.getLogger("PERCEPTION")


class PerceptionRuntime:
    def __init__(self, settings, agent, store: PerceptionStore | None = None):
        self.settings, self.agent = settings, agent
        self.store = store or PerceptionStore(settings.perception_db_path)
        self.store.fail_inflight()
        self.ledger = InteractionLedger(settings.perception_db_path,
                                        settings.interaction_ledger_ttl_hours)
        self.planner = ExternalCognitionPlanner(agent)
        self.images = ImageResolver(settings.perception_image_temp_dir,
            settings.perception_image_max_bytes, settings.perception_image_ttl_hours,
            trusted_host=urlparse(settings.qq_ws_url).hostname,
            trusted_port=urlparse(settings.qq_ws_url).port)
        self.status = "ready"
        self.direct_count = self.ignored_count = self.multimodal_input_count = 0
        self.last_observation = self.last_batch = self.last_snapshot = None
        self.last_error = None
        self.last_outbound_segment_count = 0
        self.last_received_at = self.last_sent_at = None
        self.source = None
        self._lock = asyncio.Lock()
        self._direct_lock = asyncio.Lock()
        self._recent_owner_image: dict[str, tuple[datetime, list[str], str]] = {}
        agent.context_builder.self_activity_provider = self.shared_context
        self.publish_runtime_state()

    def runtime_self_state(self) -> dict:
        qq = self.source.diagnostics() if self.source else {}
        return {"perception": {"enabled": True}, "qq": {
            "enabled": bool(self.settings.qq_enabled),
            "connected": bool(qq.get("connected")),
            "identity_verified": bool(qq.get("identity_verified")),
            "logged_in_qq": qq.get("logged_in_qq"),
            "bot_user_id": self.settings.qq_bot_user_id or None,
            "last_received_at": self.last_received_at,
            "last_sent_at": self.last_sent_at,
            "reconnect_count": qq.get("reconnect_count", 0),
            "last_error": qq.get("last_error")}}

    def publish_runtime_state(self) -> None:
        self.ledger.save_runtime_state(self.runtime_self_state())

    def shared_context(self, *, include_private: bool = True) -> str:
        import json
        state = json.dumps(self.runtime_self_state(), ensure_ascii=False, default=str)
        activity = self.ledger.context(self.settings.interaction_ledger_context_limit,
            self.settings.interaction_ledger_context_max_chars,
            include_private=include_private) if self.settings.interaction_ledger_enabled else ""
        return "[Runtime Self State]\n" + state + "\n[/Runtime Self State]\n" + activity

    async def _session(self, item):
        store = getattr(self.agent, "session_store", None)
        if store is None:
            return None
        session = await store.get_or_create(session_key(item))
        session.channel_metadata = {"channel": item.source,
            "conversation_kind": item.conversation_kind or "",
            "conversation_id": item.conversation_id or ""}
        return session

    async def _images(self, item):
        images = []
        for part in item.effective_parts:
            if part.type == "image":
                image = await self.images.resolve({"url": part.url}) if part.url else None
                if image is None and part.file:
                    image = await self.images.resolve({"file": part.file})
                if image:
                    images.append(image)
        if images:
            self.multimodal_input_count += 1
        return images

    async def ingest(self, item: Observation) -> str | None:
        decision = route(item)
        status = {AttentionHint.IGNORE: ObservationStatus.IGNORED,
                  AttentionHint.AMBIENT: ObservationStatus.BUFFERED,
                  AttentionHint.DIRECT: ObservationStatus.PENDING}[decision]
        if not self.store.insert(item, status):
            return None
        self.last_observation = self.last_received_at = item.received_at.isoformat()
        self.publish_runtime_state()
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
        if self.settings.interaction_ledger_enabled:
            is_owner_private = item.actor_role == "OWNER" and item.conversation_kind == "private"
            import json
            summary = (f"通过 QQ 私聊收到 Owner 消息：{json.dumps((item.content or '[图片]')[:180], ensure_ascii=False)}"
                       if is_owner_private else
                       f"通过 QQ {'私聊' if item.conversation_kind == 'private' else '群聊'}收到{item.actor_role}定向消息")
            self.ledger.record("external_message_received", item.source, summary,
                conversation_id=item.conversation_id, actor_role=item.actor_role,
                actor_id=item.actor_id, source_refs=item.metadata.get("merged_refs") or
                    ([item.raw_ref] if item.raw_ref else []),
                private=is_owner_private)
        try:
            async with self._direct_lock:
                session = await self._session(item)
                images = await self._images(item)
                adjacent_image_ref = None
                if item.actor_role == "OWNER" and item.conversation_kind == "private":
                    key = session_key(item)
                    recent = self._recent_owner_image.get(key)
                    if images:
                        self._recent_owner_image[key] = (datetime.now(UTC), images, item.raw_ref or "")
                    elif (recent and item.content and
                          datetime.now(UTC) - recent[0] <= timedelta(seconds=30) and
                          re.search(r"图|照片|表情|这张|刚才", item.content)):
                        images = recent[1]
                        adjacent_image_ref = recent[2]
                        self._recent_owner_image.pop(key, None)
                messages = build_external_messages(item, self.store,
                    self.agent.context_builder.character_prompt,
                    snapshot_limit=self.settings.perception_snapshot_limit,
                    max_chars=self.settings.perception_context_max_chars,
                    session=session,
                    self_context=self.shared_context(include_private=(
                        item.actor_role == "OWNER" and item.conversation_kind == "private")),
                    images=images,
                    emoji_context=(self.agent.emoji_service.build_context()
                        if getattr(self.agent, "emoji_service", None) else ""))
                if adjacent_image_ref:
                    messages.insert(1, Message(role=Role.SYSTEM,
                        content=f"本轮视觉输入是同一 Owner QQ 私聊中刚收到的图片，来源 {adjacent_image_ref}。"
                                "当前文字是在追问这张图；请根据视觉内容回答。"))
                if item.actor_role == "OWNER" and item.conversation_kind == "private":
                    cognition = getattr(self.agent, "current_cognition", None)
                    if cognition is not None:
                        messages.insert(1, Message(role=Role.SYSTEM,
                            content="[Current Cognition]\n" + cognition.snapshot() +
                                    "\n[/Current Cognition]"))
                    retriever = getattr(self.agent.context_builder, "memory_retriever", None)
                    if retriever is not None and item.content.strip():
                        try:
                            relevant = await retriever.retrieve(item.content)
                            formatted = retriever.format(relevant[:3])
                            if formatted:
                                messages.insert(1, Message(role=Role.SYSTEM,
                                    content="[Relevant Memory]\n" + formatted[:2000] +
                                            "\n[/Relevant Memory]"))
                        except Exception as exc:
                            logger.warning("external memory retrieval failed type=%s", type(exc).__name__)
                if self.settings.external_cognition_enabled:
                    try:
                        async with self.agent.conversation_lock:
                            plan = await asyncio.wait_for(self.planner.decide(item, messages), timeout=60)
                    except (json.JSONDecodeError, ValidationError) as exc:
                        # A malformed Planner response must not discard an Owner's picture.
                        # No cognition or memory candidate is applied on this path.
                        self.last_error = type(exc).__name__
                        logger.warning("planner format failed type=%s", type(exc).__name__)
                        should_reply = item.actor_role == "OWNER" and item.conversation_kind == "private"
                    else:
                        await self.planner.apply_candidates(item, plan)
                        should_reply = plan.reply
                else:
                    should_reply = True
                if session is not None:
                    label = "[Owner QQ Message]" if item.actor_role == "OWNER" else "[Third Party QQ Message]"
                    session.conversation.add(Message(role=Role.EXTERNAL,
                        content=f"{label} {item.content or '[图片]'}", source=item.source,
                        metadata={"raw_ref": item.raw_ref, "actor_role": item.actor_role}))
                    refs = item.metadata.get("merged_refs") or ([item.raw_ref] if item.raw_ref else [])
                    session.recent_message_refs = [*session.recent_message_refs,
                        *(ref for ref in refs if ref not in session.recent_message_refs)][-40:]
                    await self.agent.session_store.save(session)
                if not should_reply:
                    self.store.set_status(item.observation_id, ObservationStatus.PROCESSED)
                    return None
                async with self.agent.conversation_lock:
                    response = await asyncio.wait_for(self.agent.provider.generate(messages, []), timeout=60)
                content = (response.content or "").strip()
                if not content or response.tool_calls:
                    raise ValueError("external response missing safe text")
                self.store.set_status(item.observation_id, ObservationStatus.PROCESSED)
                return content
        except Exception as exc:
            self.store.set_status(item.observation_id, ObservationStatus.FAILED)
            self.last_error = type(exc).__name__
            logger.warning("direct failed type=%s", type(exc).__name__)
            return None

    async def reply_sent(self, item: Observation, content: str, segment_count: int) -> None:
        self.last_sent_at = datetime.now(UTC).isoformat()
        self.publish_runtime_state()
        self.last_outbound_segment_count = segment_count
        if self.settings.interaction_ledger_enabled:
            is_owner_private = item.actor_role == "OWNER" and item.conversation_kind == "private"
            import json
            summary = (f"已通过 QQ 私聊回复 Owner：{json.dumps(content[:180], ensure_ascii=False)}"
                       if is_owner_private else
                       f"已通过 QQ {'私聊' if item.conversation_kind == 'private' else '群聊'}回复{item.actor_role}")
            self.ledger.record("external_reply_sent", item.source, summary,
                conversation_id=item.conversation_id, actor_role=item.actor_role,
                actor_id=item.actor_id, source_refs=item.metadata.get("merged_refs") or
                    ([item.raw_ref] if item.raw_ref else []),
                private=is_owner_private)
        session = await self._session(item)
        if session is not None:
            session.conversation.add_assistant(content, source="qq")
            await self.agent.session_store.save(session)

    async def process_pending_snapshot(self) -> int:
        if not self.settings.external_cognition_ambient_enabled:
            return 0
        pending = self.store.pending_snapshots(1)
        if not pending:
            return 0
        snap = pending[0]
        # Snapshot content is untrusted and cannot become Owner evidence.
        item = Observation(source=snap.source, source_kind="social_snapshot",
            conversation_id=snap.conversation_id, conversation_kind="group",
            content=snap.summary, raw_ref="snapshot:" + snap.snapshot_id)
        messages = [Message(role=Role.SYSTEM,
            content=self.agent.context_builder.character_prompt + "\n" +
                    self.shared_context(include_private=False)),
            Message(role=Role.EXTERNAL,
            content=f"[External Social Snapshot] refs={snap.raw_refs}\n{snap.summary}",
            source=snap.source)]
        try:
            async with self.agent.conversation_lock:
                plan = await asyncio.wait_for(self.planner.decide(item, messages, ambient=True), timeout=60)
            await self.planner.apply_candidates(item, plan)
            self.store.set_snapshot_cognition(snap.snapshot_id, "PROCESSED")
            if plan.record_self_event and self.settings.interaction_ledger_enabled:
                self.ledger.record("snapshot_reviewed", snap.source,
                    "朝汐整理了一次 QQ 群聊摘要", conversation_id=snap.conversation_id,
                    source_refs=snap.raw_refs[:20])
            return 1
        except Exception as exc:
            self.last_error = type(exc).__name__
            logger.warning("snapshot cognition failed type=%s", type(exc).__name__)
            return 0

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
                    self.last_batch, self.last_snapshot = batch.batch_id, snapshot.snapshot_id
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
                self.ledger.clear_expired()
                self.images.clear_expired()
                self.publish_runtime_state()
        finally:
            self.status = "stopped"

    def diagnostics(self):
        sessions = getattr(self.agent, "session_store", None)
        session_count = 0
        if sessions and hasattr(sessions, "_connect"):
            with sessions._connect() as db:
                session_count = db.execute("SELECT COUNT(*) FROM sessions WHERE session_id LIKE 'qq/%'").fetchone()[0]
        return {"enabled": True, "status": self.status,
                "source_count": 1 if self.source else 0,
                "pending_observation_count": self.store.counts().get("PENDING", 0),
                "buffered_conversation_count": len(self.store.buckets()),
                "pending_perception_cognition": len(self.store.pending_snapshots(100)),
                "qq_session_count": session_count,
                "recent_self_events": [x.model_dump(mode="json") for x in self.ledger.recent(8)],
                "runtime_self_state": self.runtime_self_state(),
                "last_planner_decision": self.planner.last_decision,
                "cognition_candidate_count": self.planner.cognition_candidate_count,
                "memory_candidate_count": self.planner.memory_candidate_count,
                "rejected_candidate_count": self.planner.rejected_candidate_count,
                "multimodal_input_count": self.multimodal_input_count,
                "last_image_resolve_status": self.images.last_status,
                "last_outbound_segment_count": self.last_outbound_segment_count,
                "last_observation": self.last_observation, "last_batch": self.last_batch,
                "last_snapshot": self.last_snapshot, "direct_event_count": self.direct_count,
                "ignored_event_count": self.ignored_count, "last_error": self.last_error,
                "qq": self.source.diagnostics() if self.source else {"connected": False}}
