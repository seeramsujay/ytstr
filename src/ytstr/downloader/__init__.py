"""
Downloader and cache management components for ytstr.

Submodules are imported lazily so that, e.g., the direct playback modes never load
the DSP stack and the CLI never loads the TUI or YouTube Music client.
"""
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ytstr.downloader.cache import CacheManager, sanitize_filename
    from ytstr.downloader.ytdlp import Downloader

_EXPORTS = {
    "CacheManager": "ytstr.downloader.cache",
    "sanitize_filename": "ytstr.downloader.cache",
    "Downloader": "ytstr.downloader.ytdlp",
}

__all__ = ["CacheManager", "sanitize_filename", "Downloader"]


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
