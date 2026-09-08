"""Stable capability declarations for independently versioned Tool packages."""

from __future__ import annotations

from pydantic import BaseModel


class CapabilityDeclaration(BaseModel):
    """The runtime surfaces a package explicitly opts into."""

    tool: bool = False
    workflow: bool = False
    router_hints: bool = False
    proactive_provider: bool = False
    reflection_provider: bool = False
    state_signal_provider: bool = False

    def enabled_names(self) -> list[str]:
        return [name for name, enabled in self.model_dump().items() if enabled]
