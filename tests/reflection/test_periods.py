from datetime import UTC, date, datetime

import pytest

from zhaoxi.reflection.models import ReflectionKind
from zhaoxi.reflection.periods import PeriodResolver


@pytest.mark.parametrize(
    ("kind", "label", "start", "end"),
    [
        (ReflectionKind.DAILY, "2026-09-01", "2026-08-31T16:00:00+00:00", "2026-09-01T16:00:00+00:00"),
        (ReflectionKind.WEEKLY, "2026-W36", "2026-08-30T16:00:00+00:00", "2026-09-06T16:00:00+00:00"),
        (ReflectionKind.MONTHLY, "2026-09", "2026-08-31T16:00:00+00:00", "2026-09-30T16:00:00+00:00"),
        (ReflectionKind.SEASONAL, "2026-Q3", "2026-06-30T16:00:00+00:00", "2026-09-30T16:00:00+00:00"),
    ],
)
def test_natural_periods_use_local_boundaries(kind, label, start, end):
    period = PeriodResolver("Asia/Shanghai").resolve(kind, reference=date(2026, 9, 1))
    assert period.label == label
    assert period.start_at.isoformat() == start
    assert period.end_at.isoformat() == end


def test_datetime_reference_requires_timezone():
    with pytest.raises(ValueError, match="必须包含时区"):
        PeriodResolver().resolve(ReflectionKind.DAILY, reference=datetime(2026, 9, 1))


def test_reference_is_converted_to_display_timezone():
    period = PeriodResolver().resolve(
        ReflectionKind.DAILY, reference=datetime(2026, 8, 31, 18, tzinfo=UTC)
    )
    assert period.label == "2026-09-01"
