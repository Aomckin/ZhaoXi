from datetime import UTC, datetime

import pytest

from zhaoxi.reflection.models import EvidenceRef, ReflectionPoint


def test_evidence_normalizes_timezone():
    evidence = EvidenceRef(
        source_type="memory",
        source_name="zhaoxi-memory",
        occurred_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
        title="项目进展",
        excerpt="完成 Reflection 任务书",
        content_hash="12345678",
    )
    assert evidence.occurred_at.tzinfo == UTC


def test_evidence_rejects_naive_datetime():
    with pytest.raises(ValueError, match="必须包含时区"):
        EvidenceRef(
            source_type="memory",
            source_name="zhaoxi-memory",
            occurred_at=datetime(2026, 9, 1),
            title="项目进展",
            excerpt="完成任务书",
            content_hash="12345678",
        )


def test_fact_requires_evidence_and_inference_requires_caveat():
    with pytest.raises(ValueError, match="fact 必须引用"):
        ReflectionPoint(text="今天完成了任务", statement_type="fact")
    with pytest.raises(ValueError, match="caveat"):
        ReflectionPoint(
            text="近期可能更专注", statement_type="inference", evidence_ids=["e1"]
        )
