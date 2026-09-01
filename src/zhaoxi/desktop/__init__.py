"""Windows 10-first local desktop presence host."""


def run_desktop(settings=None) -> None:
    from zhaoxi.desktop.app import run_desktop as _run_desktop

    _run_desktop(settings)


__all__ = ["run_desktop"]
