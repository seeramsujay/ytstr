"""
YouTube Music integration and authentication.

Submodules are imported lazily so that, e.g., the direct playback modes never load
the DSP stack and the CLI never loads the TUI or YouTube Music client.
"""
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ytstr.ytm.auth import AuthManager
    from ytstr.ytm.client import YouTubeMusicClient

_EXPORTS = {
    "AuthManager": "ytstr.ytm.auth",
    "YouTubeMusicClient": "ytstr.ytm.client",
}

__all__ = ["AuthManager", "YouTubeMusicClient"]


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
