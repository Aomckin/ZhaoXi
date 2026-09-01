from datetime import UTC, datetime

import pytest

from zhaoxi.reflection.models import ReflectionKind, ReflectionRecord, ReflectionStatus
from zhaoxi.reflection.periods import PeriodResolver
from zhaoxi.reflection.sqlite import SQLiteReflectionRepository


@pytest.mark.asyncio
async def test_repository_round_trip_and_idempotency_lookup(tmp_path):
    repository = SQLiteReflectionRepository(tmp_path / "reflection.db")
    record = ReflectionRecord(
        kind=ReflectionKind.DAILY,
        period=PeriodResolver().resolve(
            ReflectionKind.DAILY, reference=datetime(2026, 9, 1, tzinfo=UTC)
        ),
        status=ReflectionStatus.COMPLETED,
        summary="今天推进了 Reflection。",
        source_fingerprint="abcdef123456",
    )
    await repository.create(record)
    loaded = await repository.get(record.reflection_id)
    assert loaded == record
    found = await repository.find_completed(
        ReflectionKind.DAILY, record.period.label, "abcdef123456", 1
    )
    assert found == record


@pytest.mark.asyncio
async def test_repository_save_list_and_revision(tmp_path):
    repository = SQLiteReflectionRepository(tmp_path / "reflection.db")
    first = ReflectionRecord(
        kind=ReflectionKind.DAILY,
        period=PeriodResolver().resolve(ReflectionKind.DAILY, reference=datetime.now(UTC)),
        source_fingerprint="abcdef123456",
    )
    await repository.create(first)
    first.status = ReflectionStatus.FAILED
    await repository.save(first)
    assert (await repository.get(first.reflection_id)).status == ReflectionStatus.FAILED
    assert [item.reflection_id for item in await repository.list()] == [first.reflection_id]


@pytest.mark.asyncio
async def test_save_missing_record_fails(tmp_path):
    repository = SQLiteReflectionRepository(tmp_path / "reflection.db")
    record = ReflectionRecord(
        kind=ReflectionKind.DAILY,
        period=PeriodResolver().resolve(ReflectionKind.DAILY, reference=datetime.now(UTC)),
        source_fingerprint="abcdef123456",
    )
    with pytest.raises(KeyError, match="不存在"):
        await repository.save(record)
