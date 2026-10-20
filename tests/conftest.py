import sys
from pathlib import Path

# Ensure src/ has precedence over repo root to avoid shadowing by ytstr.py
src_path = str(Path(__file__).resolve().parent.parent / 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)
elif sys.path[0] != src_path:
    sys.path.remove(src_path)
    sys.path.insert(0, src_path)

import pytest


@pytest.fixture(autouse=True)
def _isolate_environment(tmp_path, monkeypatch):
    """Keep tests hermetic: no network downloads, no global key hooks, no real cache dir."""
    monkeypatch.setenv("YTSTR_MEDIA_KEYS", "0")
    monkeypatch.setattr("ytstr.downloader.cache.CACHE_BASE_DIR", tmp_path / "cache")

    from ytstr.downloader.ytdlp import Downloader

    # Every yt-dlp invocation goes through Downloader._run: make it a no-op failure
    monkeypatch.setattr(Downloader, "_run", lambda self, args, timeout: None)
