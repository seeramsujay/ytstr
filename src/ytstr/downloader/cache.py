"""
Disk-backed bounded cache manager with sliding-window eviction and file-by-file export.
"""
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from ytstr.config import CACHE_BASE_DIR, ensure_cache_dir
from ytstr.core.types import Track


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe cross-platform filenames."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "untitled"


class CacheManager:
    """
    Manages bounded on-disk audio caching, pruning played tracks to keep
    storage minimal, and supporting file-by-file export when --save is specified.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        save_dir: Optional[str] = None,
        keep_cache: bool = False,
    ):
        self.session_id = session_id or str(os.getpid())
        ensure_cache_dir()
        self.session_dir = CACHE_BASE_DIR / f"session_{self.session_id}"
        self.raw_dir = self.session_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.ipc_socket = str(self.session_dir / "mpv_ipc.sock")

        self.save_dir = Path(save_dir).expanduser() if save_dir else None
        if self.save_dir:
            self.save_dir.mkdir(parents=True, exist_ok=True)

        self.keep_cache = keep_cache

    def get_track_cache_path(self, track_index: int, extension: str = "opus") -> Path:
        """Return the cache file path for a track index."""
        return self.raw_dir / f"{track_index}.{extension}"

    def track_is_cached(self, track_index: int) -> bool:
        """Check if track file exists in cache and has non-zero size."""
        for ext in ["opus", "m4a", "webm", "mp3"]:
            p = self.get_track_cache_path(track_index, ext)
            if p.exists() and p.stat().st_size > 1024:
                return True
        return False

    def find_cached_file(self, track_index: int) -> Optional[Path]:
        """Find the actual cached file regardless of extension."""
        for ext in ["opus", "m4a", "webm", "mp3"]:
            p = self.get_track_cache_path(track_index, ext)
            if p.exists() and p.stat().st_size > 1024:
                return p
        return None

    def on_track_finished(self, track_index: int, track: Optional[Track] = None):
        """
        Invoked when a track completes playback.
        If save_dir is configured, copy/move to save_dir.
        Otherwise, prune file from cache to release disk storage.
        """
        cached_file = self.find_cached_file(track_index)
        if not cached_file:
            return

        if self.save_dir and track:
            try:
                base_name = sanitize_filename(track.display_title())
                dest = self.save_dir / f"{base_name}{cached_file.suffix}"
                shutil.copy2(cached_file, dest)
            except Exception:
                pass

        if not self.keep_cache and not self.save_dir:
            try:
                cached_file.unlink(missing_ok=True)
            except Exception:
                pass

    def prune_earlier_than(self, active_index: int):
        """
        Sliding-window eviction: delete any cached tracks earlier than active_index - 1
        unless --save is enabled.
        """
        if self.keep_cache or self.save_dir:
            return

        for f in self.raw_dir.glob("*.*"):
            try:
                idx = int(f.stem)
                if idx < active_index - 1:
                    f.unlink(missing_ok=True)
            except (ValueError, OSError):
                continue

    def cleanup(self):
        """Purge temporary session files and IPC socket."""
        try:
            if self.session_dir.exists():
                shutil.rmtree(self.session_dir, ignore_errors=True)
        except Exception:
            pass
