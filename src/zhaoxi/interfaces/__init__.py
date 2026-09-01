"""Unified local interface boundary for CLI, Web, and Desktop clients."""

from zhaoxi.interfaces.gateway import InterfaceGateway
from zhaoxi.interfaces.models import (
    InterfaceChannel,
    MessageOrigin,
    PermissionView,
    UnifiedMessage,
    UnifiedResponse,
)

__all__ = [
    "InterfaceChannel",
    "InterfaceGateway",
    "MessageOrigin",
    "PermissionView",
    "UnifiedMessage",
    "UnifiedResponse",
]
