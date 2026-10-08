"""Regression coverage for ambient budget isolation and persistent failed-head recovery."""
import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from zhaoxi.config.settings import Settings
from zhaoxi.errors import ProviderError
from zhaoxi.internal_activity.activities.legacy import PERCEPTION_COGNITION
from zhaoxi.internal_activity.runtime import InternalActivityRuntime
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.perception.models import ObservationBatch, SocialSnapshot
from zhaoxi.perception.runtime import PerceptionRuntime
from zhaoxi.perception.store import PerceptionStore
from zhaoxi.reliability.retry import current_budget


def snapshot(store, key, at=None, summary="群友正在聊晚餐"):
    at = at or datetime.now(UTC)
    batch = ObservationBatch(batch_id="batch-" + key, source="qq", conversation_id="123",
                             window_start=at, window_end=at, observation_ids=[], raw_refs=[])
    item = SocialSnapshot(snapshot_id=key, batch_id=batch.batch_id, source="qq", conversation_id="123",
                          window_start=at, window_end=at, message_count=2, summary=summary,
                          observation_ids=[], raw_refs=[], confidence=.5)
    store.commit_batch(batch, item)
    return item


def cognition_row(store, key):
    with store._connect() as db:
        return dict(db.execute("SELECT * FROM snapshot_cognition WHERE snapshot_id=?", (key,)).fetchone())


def make_runtime(tmp_path, generate):
    settings = Settings(_env_file=None, perception_db_path=str(tmp_path / "perception.db"),
                        media_directory=str(tmp_path / "media"), perception_image_temp_dir=str(tmp_path / "images"),
                        presence_v2_enabled=False, decision_learning_enabled=False,
                        current_cognition_consolidation_enabled=False, memory_maintenance_enabled=False,
                        agenda_maintenance_enabled=False, proactive_activity_enabled=False)
    agent = SimpleNamespace(provider=ResilientProvider([SimpleNamespace(generate=generate)]),
                            conversation_lock=asyncio.Lock(),
                            context_builder=SimpleNamespace(build=Mock(side_effect=AssertionError("full private context used"))))
    runtime = PerceptionRuntime(settings, agent)
    agent.perception = runtime
    activity = InternalActivityRuntime(agent, settings, tmp_path / "activity.db")
    return runtime, activity


def test_legacy_schema_migration_preserves_pending_and_is_idempotent(tmp_path):
    path = tmp_path / "perception.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE snapshot_cognition (snapshot_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'PENDING')")
        db.execute("INSERT INTO snapshot_cognition VALUES ('old', 'PENDING')")
    store = PerceptionStore(path)
    assert cognition_row(store, "old") == dict(snapshot_id="old", status="PENDING", attempt_count=0,
                                              next_retry_at=None, last_error=None)
    assert cognition_row(PerceptionStore(path), "old")["attempt_count"] == 0


def test_retry_queue_survives_restart_skips_head_and_quarantines(tmp_path):
    store = PerceptionStore(tmp_path / "perception.db")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    bad = snapshot(store, "bad", now, summary="原摘要必须保留")
    snapshot(store, "good", now + timedelta(seconds=1))
    first = store.record_snapshot_failure("bad", "provider_token_budget_exhausted", now=now)
    assert first["attempt_count"] == 1 and first["next_retry_at"] == (now + timedelta(minutes=5)).isoformat()
    store = PerceptionStore(store.path)
    assert [x.snapshot_id for x in store.pending_snapshots(now=now)] == ["good"]
    assert store.snapshot_cognition_counts() == {"PENDING": 2}
    assert [x.snapshot_id for x in store.pending_snapshots(now=now + timedelta(minutes=5))] == ["bad", "good"]
    second = store.record_snapshot_failure("bad", "TimeoutError", now=now + timedelta(minutes=5))
    assert second["next_retry_at"] == (now + timedelta(minutes=15)).isoformat()
    third = store.record_snapshot_failure("bad", "ValueError", now=now + timedelta(minutes=15))
    assert third["status"] == "FAILED" and third["attempt_count"] == 3 and third["next_retry_at"] is None
    assert [x.snapshot_id for x in store.pending_snapshots(now=now + timedelta(days=1))] == ["good"]
    assert store.snapshot_cognition_counts() == {"FAILED": 1, "PENDING": 1}
    assert next(x for x in store.recent_all_snapshots() if x.snapshot_id == "bad") == bad
    store.set_snapshot_cognition("bad", "PENDING")
    assert cognition_row(store, "bad")["attempt_count"] == 0
    assert cognition_row(store, "bad")["last_error"] is None
    assert store.pending_snapshots(now=now)[0].snapshot_id == "bad"


@pytest.mark.asyncio
async def test_budget_and_bounded_context_with_real_resilient_accounting(tmp_path):
    calls = []
    async def generate(messages, tools, **options):
        calls.append((messages, tools, options, current_budget().max_total_tokens))
        # An actual usage report above the previous 6000 budget must be accepted.
        return ModelResponse(content='{"reply":false,"reason":"summary reviewed"}',
                             usage={"prompt_tokens": 7000, "completion_tokens": 1000, "total_tokens": 8000})
    runtime, activity = make_runtime(tmp_path, generate)
    snapshot(runtime.store, "bounded", summary="晚餐讨论" * 20_000)
    await activity.run_tick(force=PERCEPTION_COGNITION)
    assert activity.state[PERCEPTION_COGNITION]["last_result"] == "UPDATE"
    assert cognition_row(runtime.store, "bounded")["status"] == "PROCESSED"
    messages, tools, options, budget = calls[0]
    assert budget == 12_000 and tools == []
    assert len(messages) == 2 and sum(len(m.content) for m in messages) < 3000
    evidence = json.loads(messages[1].content.split("\n", 1)[1])
    assert evidence["raw_ref"] == "snapshot:bounded" and evidence["summary_truncated"] is True
    assert options["max_tokens"] == 1024 and options["reasoning_budget_tokens"] == 2048
    runtime.agent.context_builder.build.assert_not_called()
    assert current_budget() is None
    assert activity.registry.get("current_cognition_consolidation").max_total_tokens == 6000


@pytest.mark.asyncio
async def test_failure_is_reported_then_later_item_progresses(tmp_path):
    calls = []
    async def generate(messages, tools, **options):
        calls.append(messages)
        if len(calls) == 1:
            raise ProviderError("bad configuration", code="unsupported_model", retryable=False)
        return ModelResponse(content='{"reply":false}')
    runtime, activity = make_runtime(tmp_path, generate)
    now = datetime.now(UTC)
    snapshot(runtime.store, "bad", now)
    snapshot(runtime.store, "good", now + timedelta(seconds=1))
    await activity.run_tick(force=PERCEPTION_COGNITION)
    assert activity.state[PERCEPTION_COGNITION]["last_result"] == "FAILED"
    assert activity.state[PERCEPTION_COGNITION]["failure_count"] == 1
    assert activity.state[PERCEPTION_COGNITION]["last_success_at"] is None
    assert activity.tick_receipts[-1]["status"] == "FAILED"
    assert cognition_row(runtime.store, "bad")["last_error"] == "unsupported_model"
    assert runtime.diagnostics()["pending_perception_cognition"] == 2
    await activity.run_tick(force=PERCEPTION_COGNITION)
    assert len(calls) == 2
    assert cognition_row(runtime.store, "good")["status"] == "PROCESSED"
    assert cognition_row(runtime.store, "bad")["attempt_count"] == 1
    assert activity.state[PERCEPTION_COGNITION]["failure_count"] == 0
    await activity.run_tick(force=PERCEPTION_COGNITION)
    assert len(calls) == 2  # Debug force cannot bypass the item's persisted retry delay.


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), ValueError("invalid JSON")])
async def test_timeout_and_protocol_failure_are_deferred_and_propagated(tmp_path, error):
    runtime, _ = make_runtime(tmp_path, AsyncMock())
    snapshot(runtime.store, "failed")
    runtime.planner.decide = AsyncMock(side_effect=error)
    with pytest.raises(type(error)):
        await runtime.process_pending_snapshot()
    row = cognition_row(runtime.store, "failed")
    assert row["status"] == "PENDING" and row["attempt_count"] == 1
    assert row["last_error"] == type(error).__name__
    assert await runtime.process_pending_snapshot() == 0
    assert runtime.planner.decide.await_count == 1


@pytest.mark.asyncio
async def test_token_overrun_remains_failure_and_records_original_budget_code(tmp_path):
    async def generate(messages, tools, **options):
        return ModelResponse(content='{"reply":false}', usage={"total_tokens": 12_001})
    runtime, activity = make_runtime(tmp_path, generate)
    snapshot(runtime.store, "overrun")
    await activity.run_tick(force=PERCEPTION_COGNITION)
    assert activity.state[PERCEPTION_COGNITION]["last_result"] == "FAILED"
    assert cognition_row(runtime.store, "overrun")["last_error"] == "provider_token_budget_exhausted"
    assert activity.tick_receipts[-1]["raw_payload"]["error_code"] == "provider_token_budget_exhausted"


@pytest.mark.asyncio
async def test_foreground_cancellation_does_not_consume_snapshot_attempt(tmp_path):
    entered = asyncio.Event()
    async def generate(messages, tools, **options):
        entered.set()
        await asyncio.Event().wait()
    runtime, _ = make_runtime(tmp_path, generate)
    snapshot(runtime.store, "interrupted")
    task = asyncio.create_task(runtime.process_pending_snapshot())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cognition_row(runtime.store, "interrupted")["attempt_count"] == 0
    assert runtime.store.pending_snapshots()[0].snapshot_id == "interrupted"


@pytest.mark.asyncio
async def test_concurrent_processing_does_not_review_same_snapshot_twice(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def generate(messages, tools, **options):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return ModelResponse(content='{"reply":false}')
    runtime, _ = make_runtime(tmp_path, generate)
    snapshot(runtime.store, "once")
    first = asyncio.create_task(runtime.process_pending_snapshot())
    await entered.wait()
    second = asyncio.create_task(runtime.process_pending_snapshot())
    release.set()
    assert await asyncio.gather(first, second) == [1, 0]
    assert calls == 1


def test_snapshot_failures_do_not_back_off_other_queue_items(tmp_path):
    _, activity = make_runtime(tmp_path, AsyncMock())
    activity.control.update("configs", {"min_interval_minutes": 1}, name=PERCEPTION_COGNITION)
    activity.state[PERCEPTION_COGNITION]["failure_count"] = 4
    assert activity._cooldown(PERCEPTION_COGNITION) == timedelta(minutes=1)


@pytest.mark.asyncio
async def test_final_failure_keeps_receipt_but_clears_unrunnable_debt(tmp_path):
    async def generate(messages, tools, **options):
        raise ProviderError("invalid model", code="unsupported_model", retryable=False)
    runtime, activity = make_runtime(tmp_path, generate)
    snapshot(runtime.store, "quarantined")
    runtime.settings.perception_cognition_max_attempts = 1
    await activity.run_tick(force=PERCEPTION_COGNITION)
    state = activity.state[PERCEPTION_COGNITION]
    assert state["last_result"] == "FAILED" and state["failure_count"] == 1
    assert state["dirty"] is False
    assert activity.tick_receipts[-1]["status"] == "FAILED"
    assert runtime.diagnostics()["snapshot_cognition_counts"] == {"FAILED": 1}
    restored = InternalActivityRuntime(activity.agent, activity.settings, activity.path)
    assert restored.state[PERCEPTION_COGNITION]["dirty"] is False
