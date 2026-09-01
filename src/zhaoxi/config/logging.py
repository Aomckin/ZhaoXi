"""Logging configuration."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from zhaoxi.reliability.context import current_correlation


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = current_correlation()
        record.trace_id = context.trace_id if context else "-"
        record.request_id = context.request_id if context and context.request_id else "-"
        return True


def configure_logging(
    level: str = "INFO",
    *,
    path: str | Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure concise application logs without exposing credentials."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if path:
        log_path = Path(path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        ))
    correlation_filter = CorrelationFilter()
    for handler in handlers:
        handler.addFilter(correlation_filter)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] trace=%(trace_id)s request=%(request_id)s %(message)s",
        handlers=handlers,
        force=True,
    )
