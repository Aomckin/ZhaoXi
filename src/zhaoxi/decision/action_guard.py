"""Execution boundary only. This guard never changes a recommendation."""

from dataclasses import dataclass
from zhaoxi.permission.models import PermissionLevel, SideEffect


@dataclass(frozen=True)
class ActionBoundary:
    flags: tuple[str, ...] = ()
    requires_confirmation: bool = False


def guard_action(permission: PermissionLevel, side_effects: frozenset[SideEffect],
                 *, high_impact: bool = False) -> ActionBoundary:
    if permission is PermissionLevel.READ:
        return ActionBoundary()
    flags = []
    if permission is PermissionLevel.DANGEROUS:
        flags.append("dangerous_action")
    if permission is PermissionLevel.DELETE or SideEffect.DATA_DELETION in side_effects:
        flags.append("irreversible_deletion")
    if (permission is PermissionLevel.EXTERNAL_ACTION or SideEffect.EXTERNAL_COMMUNICATION in side_effects
            or high_impact and SideEffect.EXTERNAL_SERVICE_WRITE in side_effects):
        flags.append("external_action")
    if SideEffect.SYSTEM_CHANGE in side_effects:
        flags.append("system_change")
    if high_impact:
        flags.append("high_impact_action")
    return ActionBoundary(tuple(flags), bool(flags))
