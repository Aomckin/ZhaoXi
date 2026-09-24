"""Turn-scoped inputs that must not enter model-generated Tool arguments or audit logs."""

from contextvars import ContextVar


current_image_attachments: ContextVar[tuple[str, ...]] = ContextVar(
    "current_image_attachments", default=()
)


def current_turn_images() -> tuple[str, ...]:
    """Return current-message images only while a Tool is executing."""
    return current_image_attachments.get()
