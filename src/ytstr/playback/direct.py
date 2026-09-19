"""
Direct MPV playback engine for ultra-low RAM sequential playback (--no-mix & --stream).
Bypasses Python audio decoding completely, achieving minimal memory footprint (< 25 MB RSS).
"""
from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable, List, Optional

from ytstr.core.types import Track
from ytstr.downloader.cache import CacheManager
from ytstr.downloader.ytdlp import Downloader
from ytstr.playback.mpv_ipc import MPVIPCClient, spawn_mpv_process


class DirectPlayer:
    """
    Direct mpv player that streams URLs or plays disk-cached files natively
    without loading raw PCM into Python process memory.
    """

    def __init__(
        self,
        tracks: List[Track],
        cache_manager: CacheManager,
        downloader: Downloader,
        direct_stream: bool = False,
        on_track_change: Optional[Callable[[int, Track], None]] = None,
    ):
        self.tracks = tracks
        self.cache_mgr = cache_manager
        self.downloader = downloader
        self.direct_stream = direct_stream
        self.on_track_change = on_track_change

        self.playing_idx = 0
        self.downloaded_idx = -1
        self._quit_flag = False

        self.skip_to_next = False
        self.skip_to_prev = False
        self.toggle_pause = False

        self.mpv_process: Optional[subprocess.Popen] = None
        self.ipc: Optional[MPVIPCClient] = None

    def start(self) -> threading.Thread:
        """Initialize mpv process and worker threads."""
        self.mpv_process = spawn_mpv_process(self.cache_mgr.ipc_socket, raw_pcm_mode=False)
        self.ipc = MPVIPCClient(self.cache_mgr.ipc_socket)

        if not self.direct_stream:
            # Prefetch thread for disk caching
            t_down = threading.Thread(target=self._download_worker, daemon=True)
            t_down.start()

        # Playback supervisor thread
        t_play = threading.Thread(target=self._playback_loop, daemon=True)
        t_play.start()
        return t_play

    def _download_worker(self) -> None:
        """Worker thread to download up to 2 tracks ahead onto disk."""
        while not self._quit_flag and self.downloaded_idx < len(self.tracks) - 1:
            if self.downloaded_idx <= self.playing_idx + 1:
                target_idx = self.downloaded_idx + 1
                if target_idx < len(self.tracks):
                    track = self.tracks[target_idx]
                    target_path = self.cache_mgr.get_track_cache_path(target_idx, "opus")

                    if not self.cache_mgr.track_is_cached(target_idx):
                        self.downloader.download_track(track, target_path)

                    self.downloaded_idx = target_idx
            else:
                time.sleep(0.5)

    def _resolve_track_target(self, idx: int) -> Optional[str]:
        """Resolve either direct stream URL or disk cached path."""
        if idx >= len(self.tracks):
            return None

        track = self.tracks[idx]
        if self.direct_stream:
            stream_url = self.downloader.get_direct_stream_url(track.id)
            if stream_url:
                return stream_url
            # Fallback to ytdl protocol in mpv
            return f"ytdl://{track.id}"

        # Wait for file download
        for _ in range(60):
            if self._quit_flag:
                return None
            cached = self.cache_mgr.find_cached_file(idx)
            if cached and cached.exists():
                return str(cached)
            time.sleep(0.2)
        return None

    def _playback_loop(self) -> None:
        """Supervisor loop managing mpv track queue, skips, and position tracking."""
        while not self._quit_flag and self.playing_idx < len(self.tracks):
            curr_idx = self.playing_idx
            curr_track = self.tracks[curr_idx]

            target = self._resolve_track_target(curr_idx)
            if not target:
                # If resolving failed, skip to next track
                self.playing_idx += 1
                continue

            if self.on_track_change:
                self.on_track_change(curr_idx, curr_track)

            # Load into MPV
            if self.ipc:
                self.ipc.load_file(target, mode="replace")

            # Playback monitoring loop for current track
            track_ended = False
            has_started = False

            while not self._quit_flag and not track_ended:
                if self.skip_to_next:
                    self.skip_to_next = False
                    break

                if self.skip_to_prev:
                    self.skip_to_prev = False
                    self.playing_idx = max(0, curr_idx - 2)
                    break

                if self.toggle_pause:
                    self.toggle_pause = False
                    if self.ipc:
                        self.ipc.cycle_pause()

                # Check mpv status
                if self.ipc:
                    playback_time = self.ipc.get_float_property("playback-time", default=0.0)
                    eof_reached = self.ipc.get_bool_property("eof-reached", default=False)
                    idle_active = self.ipc.get_bool_property("idle-active", default=False)

                    if playback_time > 0.5:
                        has_started = True

                    if has_started and (eof_reached or idle_active):
                        track_ended = True
                        break

                time.sleep(0.25)

            # Track completed or skipped: trigger cache cleanup / save
            if not self.direct_stream:
                self.cache_mgr.on_track_finished(curr_idx, curr_track)
                self.cache_mgr.prune_earlier_than(curr_idx)

            self.playing_idx += 1

    def stop(self) -> None:
        """Terminate mpv and cleanup resources."""
        self._quit_flag = True
        if self.ipc:
            try:
                self.ipc.stop()
                self.ipc.close()
            except Exception:
                pass
            self.ipc = None

        if self.mpv_process:
            try:
                self.mpv_process.terminate()
                self.mpv_process.wait(timeout=1.0)
            except Exception:
                try:
                    self.mpv_process.kill()
                except Exception:
                    pass
            self.mpv_process = None
