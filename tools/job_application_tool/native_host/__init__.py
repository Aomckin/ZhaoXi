"""Native Messaging host package."""

__all__ = ["NativeHostBroker"]


def __getattr__(name: str):
    if name == "NativeHostBroker":
        from tools.job_application_tool.native_host.host import NativeHostBroker
        return NativeHostBroker
    raise AttributeError(name)
