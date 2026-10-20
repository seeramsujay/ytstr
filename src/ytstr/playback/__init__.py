"""
Playback controllers for direct low-RAM mpv and streaming DJ transition pipelines.

Submodules are imported lazily so that, e.g., the direct playback modes never load
the DSP stack and the CLI never loads the TUI or YouTube Music client.
"""
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ytstr.playback.direct import DirectPlayer
    from ytstr.playback.dj_player import DJPlayer
    from ytstr.playback.mpv_ipc import MPVIPCClient, spawn_mpv_process

_EXPORTS = {
    "DirectPlayer": "ytstr.playback.direct",
    "DJPlayer": "ytstr.playback.dj_player",
    "MPVIPCClient": "ytstr.playback.mpv_ipc",
    "spawn_mpv_process": "ytstr.playback.mpv_ipc",
}

__all__ = ["DirectPlayer", "DJPlayer", "MPVIPCClient", "spawn_mpv_process"]


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
