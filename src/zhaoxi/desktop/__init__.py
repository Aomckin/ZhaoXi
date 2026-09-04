"""Windows 10-first local desktop presence host."""


def run_desktop(settings=None, *, background=False) -> None:
    from zhaoxi.desktop.app import run_desktop as _run_desktop

    _run_desktop(settings, background=background)


__all__ = ["run_desktop"]
