"""Timezone-aware natural Reflection period resolution."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zhaoxi.reflection.models import ReflectionKind, ReflectionPeriod


class PeriodResolver:
    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        try:
            self.zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区：{timezone}") from exc
        self.timezone = timezone

    def resolve(
        self,
        kind: ReflectionKind,
        *,
        reference: datetime | date | None = None,
        project_ref: str | None = None,
    ) -> ReflectionPeriod:
        local = self._local_date(reference)
        if kind == ReflectionKind.DAILY:
            start, end, label = local, local + timedelta(days=1), local.isoformat()
        elif kind == ReflectionKind.WEEKLY:
            start = local - timedelta(days=local.weekday())
            end = start + timedelta(days=7)
            iso_year, iso_week, _ = start.isocalendar()
            label = f"{iso_year}-W{iso_week:02d}"
        elif kind == ReflectionKind.MONTHLY:
            start = local.replace(day=1)
            end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
            label = f"{start.year}-{start.month:02d}"
        elif kind == ReflectionKind.SEASONAL:
            quarter = (local.month - 1) // 3 + 1
            start = date(local.year, (quarter - 1) * 3 + 1, 1)
            end = date(local.year + (quarter == 4), 1 if quarter == 4 else quarter * 3 + 1, 1)
            label = f"{local.year}-Q{quarter}"
        elif kind in {ReflectionKind.PROJECT, ReflectionKind.DREAM}:
            start, end = local - timedelta(days=29), local + timedelta(days=1)
            label = f"{start.isoformat()}..{local.isoformat()}"
        else:  # pragma: no cover - StrEnum makes this defensive
            raise ValueError(f"不支持的 reflection kind：{kind}")
        return ReflectionPeriod(
            start_at=datetime.combine(start, time.min, self.zone),
            end_at=datetime.combine(end, time.min, self.zone),
            timezone=self.timezone,
            label=label,
            project_ref=project_ref,
        )

    def _local_date(self, value: datetime | date | None) -> date:
        if value is None:
            return datetime.now(self.zone).date()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("reference datetime 必须包含时区")
            return value.astimezone(self.zone).date()
        return value
