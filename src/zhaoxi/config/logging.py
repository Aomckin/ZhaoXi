"""Logging configuration."""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure concise application logs without exposing credentials."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
