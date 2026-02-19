"""
Background preloader for heavy lerobot modules.

Starts importing lerobot (torch, transformers, etc.) in a daemon thread while
the user is still answering interactive prompts.  When calibration / motor-setup
functions later do the same imports they resolve instantly from sys.modules.
"""

import threading
from rich.console import Console

_console = Console()
_preload_done = threading.Event()


def _preload_lerobot_imports():
    """Import heavy lerobot modules in the background."""
    try:
        import lerobot.scripts.lerobot_calibrate  # noqa: F401
        import lerobot.teleoperators  # noqa: F401
        import lerobot.robots  # noqa: F401
    except Exception:
        pass  # errors will surface later when the real import happens
    finally:
        _preload_done.set()


def start_lerobot_preload():
    """Kick off background import if not already done."""
    if not _preload_done.is_set():
        t = threading.Thread(target=_preload_lerobot_imports, daemon=True)
        t.start()


def wait_for_lerobot_preload():
    """Block until the background import finishes (with a spinner if needed)."""
    if not _preload_done.is_set():
        with _console.status("Loading calibration libraries...", spinner="dots"):
            _preload_done.wait()

