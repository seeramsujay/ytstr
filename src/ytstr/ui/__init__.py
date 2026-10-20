"""
Terminal user interfaces for ytstr.

Submodules are imported lazily so that, e.g., the direct playback modes never load
the DSP stack and the CLI never loads the TUI or YouTube Music client.
"""
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ytstr.ui.tui import TUIApp, main

_EXPORTS = {
    "TUIApp": "ytstr.ui.tui",
    "main": "ytstr.ui.tui",
}

__all__ = ["TUIApp", "main"]


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
