"""
Direct MPV playback engine for ultra-low RAM sequential playback (--no-mix & --stream).
Bypasses Python audio decoding completely, achieving minimal memory footprint (< 25 MB RSS).
Features prioritized sliding window caching, instant jump-to-index, and rewind capabilities.
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
        self.tracks = list(tracks)
        self.cache_mgr = cache_manager
        self.downloader = downloader
        self.direct_stream = direct_stream
        self.on_track_change = on_track_change

        self.playing_idx = 0
        self._quit_flag = False

        self.skip_to_next = False
        self.skip_to_prev = False
        self.jump_to_idx: Optional[int] = None
        self.toggle_pause = False

        self.mpv_process: Optional[subprocess.Popen] = None
        self.ipc: Optional[MPVIPCClient] = None

    def start(self) -> threading.Thread:
        """Initialize mpv process and worker threads."""
        self.mpv_process = spawn_mpv_process(self.cache_mgr.ipc_socket, raw_pcm_mode=False)
        self.ipc = MPVIPCClient(self.cache_mgr.ipc_socket)

        if not self.direct_stream:
            # Prefetch thread for disk caching
            t_down = threading.Thread(target=self._download_worker, daemon=True, name="ytstr-direct-download")
            t_down.start()

        # Playback supervisor thread
        t_play = threading.Thread(target=self._playback_loop, daemon=True, name="ytstr-direct-play")
        t_play.start()
        return t_play

    def jump_to(self, target_idx: int) -> None:
        """Jump playback immediately to target index without discarding tracks."""
        if 0 <= target_idx < len(self.tracks):
            self.jump_to_idx = target_idx
            self.skip_to_next = True

    def _download_worker(self) -> None:
        """
        Prefetches audio files for active sliding window:
        Prioritizes current track, next two tracks, and previous track (< 30 MB).
        """
        while not self._quit_flag:
            total_tracks = len(self.tracks)
            curr_playing = self.playing_idx

            if total_tracks == 0:
                time.sleep(0.4)
                continue

            targets = [curr_playing, curr_playing + 1, curr_playing + 2]
            if curr_playing > 0:
                targets.append(curr_playing - 1)

            downloaded_something = False
            for idx in targets:
                if self._quit_flag or self.jump_to_idx is not None:
                    break
                if 0 <= idx < total_tracks:
                    track = self.tracks[idx]
                    if not self.cache_mgr.track_is_cached(track):
                        target_path = self.cache_mgr.get_track_cache_path(track, "opus")
                        self.downloader.download_track(track, target_path)
                        downloaded_something = True
                        break

            self.cache_mgr.prune_window(curr_playing, self.tracks)

            if not downloaded_something:
                time.sleep(0.4)

    def _resolve_track_target(self, idx: int) -> Optional[str]:
        """Resolve either direct stream URL or disk cached path."""
        if idx >= len(self.tracks):
            return None

        track = self.tracks[idx]
        if self.direct_stream:
            stream_url = self.downloader.get_direct_stream_url(track.id)
            if stream_url:
                return stream_url
            return f"ytdl://{track.id}"

        # Check disk cache first for instantaneous startup
        cached = self.cache_mgr.find_cached_file(track)
        if cached and cached.exists():
            return str(cached)

        # Fallback to direct stream URL while background worker caches
        stream_url = self.downloader.get_direct_stream_url(track.id)
        if stream_url:
            return stream_url

        return track.web_url

    def _playback_loop(self) -> None:
        """Supervisor loop managing mpv track queue, skips, and position tracking."""
        while not self._quit_flag and self.playing_idx < len(self.tracks):
            if self.jump_to_idx is not None:
                self.playing_idx = self.jump_to_idx
                self.jump_to_idx = None
                continue

            curr_idx = self.playing_idx
            curr_track = self.tracks[curr_idx]

            target = self._resolve_track_target(curr_idx)
            if not target:
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
                if self.jump_to_idx is not None:
                    break

                if self.skip_to_next:
                    self.skip_to_next = False
                    self.playing_idx += 1
                    track_ended = True
                    break

                if self.skip_to_prev:
                    self.skip_to_prev = False
                    self.playing_idx = max(0, curr_idx - 1)
                    track_ended = True
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
                        self.playing_idx += 1
                        break

                time.sleep(0.25)

            # Track completed: notify cache manager and prune window
            if not self.direct_stream:
                self.cache_mgr.on_track_finished(curr_idx, curr_track)
                self.cache_mgr.prune_window(self.playing_idx, self.tracks)

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
