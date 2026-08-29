"""Backward-compatible import for v0.1 session storage."""

from zhaoxi.session.in_memory import InMemorySessionStore

__all__ = ["InMemorySessionStore"]
