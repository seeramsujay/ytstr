"""
Thread-safe disk caching and sliding-window cache management for audio streams.
Ensures memory safety (< 30 MB process memory) and prevents redundant network requests.
Supports prioritized retention: active track, next 2 songs, and previous song (< 30 MB).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Union

from ytstr.config import CACHE_BASE_DIR, MAX_PREFETCH_TRACKS
from ytstr.core.types import Track

logger = logging.getLogger(__name__)

# Strict 30 MB size threshold for keeping previous completed tracks in cache
MAX_CACHE_TRACK_SIZE_BYTES: int = 30 * 1024 * 1024


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe cross-platform filenames."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "untitled"


class CacheManager:
    """
    Manages session-scoped audio file cache on disk.
    Applies sliding-window retention:
    - Retains currently playing track.
    - Retains next two upcoming tracks.
    - Retains previous track ONLY IF its size is <= 30 MB.
    - Prunes all other older or distant tracks to keep disk footprint bounded.
    """

    def __init__(
        self,
        session_id: str,
        keep_cache: bool = False,
        save_dir: Optional[Union[str, Path]] = None,
    ):
        self.session_id = session_id
        self.keep_cache = keep_cache
        self.save_dir = Path(save_dir) if save_dir else None
        if self.save_dir:
            self.save_dir.mkdir(parents=True, exist_ok=True)

        self.session_dir = CACHE_BASE_DIR / f"ytstr_session_{self.session_id}"
        self.raw_dir = self.session_dir / "raw"
        self.ipc_socket = f"/tmp/ytstr_mpv_{self.session_id}.sock"

        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def get_track_cache_path(self, target: Union[int, str, Track], extension: str = "opus") -> Path:
        """
        Generate disk cache destination path.
        Prioritizes track ID to avoid queue index re-mapping collisions.
        """
        if isinstance(target, Track):
            key = sanitize_filename(target.id if target.id else target.display_title())
        elif isinstance(target, str):
            key = sanitize_filename(target)
        else:
            key = str(target)
        return self.raw_dir / f"{key}.{extension}"

    def track_is_cached(self, target: Union[int, str, Track]) -> bool:
        """Check if track file exists in cache and has non-zero size."""
        return self.find_cached_file(target) is not None

    def find_cached_file(self, target: Union[int, str, Track]) -> Optional[Path]:
        """
        Find the actual cached file on disk regardless of audio container extension.
        Checks track ID, track file_path, and numerical index fallback.
        """
        # If target has a pre-assigned file_path that exists
        if isinstance(target, Track) and target.file_path:
            p = Path(target.file_path)
            if p.exists() and p.stat().st_size > 1024:
                return p

        # Check primary key
        for ext in ["opus", "m4a", "webm", "mp3"]:
            p = self.get_track_cache_path(target, ext)
            if p.exists() and p.stat().st_size > 1024:
                return p

        # If target is Track, also check by its string ID directly
        if isinstance(target, Track) and target.id:
            for ext in ["opus", "m4a", "webm", "mp3"]:
                p = self.raw_dir / f"{sanitize_filename(target.id)}.{ext}"
                if p.exists() and p.stat().st_size > 1024:
                    return p

        return None

    def on_track_finished(self, track_index: int, track: Optional[Track] = None) -> None:
        """
        Invoked when a track completes playback.
        If save_dir is configured, copy to save_dir.
        Retains previous track in cache if its size is <= 30 MB; evicts if > 30 MB.
        """
        target = track if track is not None else track_index
        cached_file = self.find_cached_file(target)
        if not cached_file and track is not None:
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

        # If cache is not kept and previous song exceeds 30 MB, prune it immediately
        if not self.keep_cache and not self.save_dir:
            try:
                size = cached_file.stat().st_size
                if size > MAX_CACHE_TRACK_SIZE_BYTES:
                    cached_file.unlink(missing_ok=True)
            except Exception:
                pass

    def prune_window(self, active_index: int, tracks: Optional[List[Track]] = None) -> None:
        """
        Enforce strict sliding window cache retention:
        - Keeps active track (active_index)
        - Keeps next two tracks (active_index + 1, active_index + 2)
        - Keeps previous track (active_index - 1) ONLY IF file size <= 30 MB
        - Deletes all other tracks to bound disk usage.
        """
        if self.keep_cache or self.save_dir or not self.raw_dir.exists():
            return

        valid_keys = set()
        prev_keys = set()

        # Previous track: active_index - 1
        if active_index > 0:
            prev_keys.add(str(active_index - 1))
            if tracks and active_index - 1 < len(tracks):
                t = tracks[active_index - 1]
                prev_keys.add(sanitize_filename(t.id if t.id else t.display_title()))
                if t.id:
                    prev_keys.add(sanitize_filename(t.id))

        # Active track and next two tracks
        for idx in range(active_index, active_index + 3):
            valid_keys.add(str(idx))
            if tracks and idx < len(tracks):
                t = tracks[idx]
                valid_keys.add(sanitize_filename(t.id if t.id else t.display_title()))
                if t.id:
                    valid_keys.add(sanitize_filename(t.id))

        try:
            for p in self.raw_dir.iterdir():
                if not p.is_file():
                    continue
                stem = p.stem

                # If file belongs to previous track, check the 30 MB limit
                if stem in prev_keys:
                    try:
                        if p.stat().st_size > MAX_CACHE_TRACK_SIZE_BYTES:
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue

                # If file belongs to active or next two tracks, keep it
                if stem in valid_keys:
                    continue

                # Evict all other files
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Error pruning cache window: %s", e)

    def prune_earlier_than(self, active_index: int) -> None:
        """Legacy helper for backward compatibility."""
        self.prune_window(active_index)

    def cleanup(self) -> None:
        """Clean up session directory and IPC socket."""
        if os.path.exists(self.ipc_socket):
            try:
                os.unlink(self.ipc_socket)
            except OSError:
                pass

        if not self.keep_cache and self.session_dir.exists():
            try:
                shutil.rmtree(self.session_dir, ignore_errors=True)
            except Exception as e:
                logger.debug("Error cleaning session dir: %s", e)
