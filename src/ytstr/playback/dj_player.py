"""
Auto-DJ and Light-Mix audio player streaming raw PCM over stdin to MPV via Bounded Hysteresis.
Features dynamic transitions, real-time volume ducking, timeline progress synchronization,
jump-to-index support, and prioritized window caching (current, next two, previous < 30 MB).
"""
from __future__ import annotations

import gc
import logging
import os
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydub import AudioSegment

from ytstr.audio.dsp import get_audio_chunk, get_audio_duration
from ytstr.audio.engine import DecisionEngine
from ytstr.audio.transitions import apply_transition
from ytstr.config import (
    DEFAULT_CROSSFADE_SEC,
    HIGH_WATERMARK_SEC,
    LOW_WATERMARK_SEC,
    STREAM_CHUNK_SEC,
)
from ytstr.core.types import Track, TransitionType
from ytstr.downloader.cache import CacheManager
from ytstr.downloader.ytdlp import Downloader
from ytstr.playback.mpv_ipc import MPVIPCClient, spawn_mpv_process

logger = logging.getLogger(__name__)


class DJPlayer:
    """
    Manages continuous seamless audio playback with psychoacoustic transitions.
    Decodes audio into memory only in bounded chunks, streaming raw 16-bit 44.1kHz
    stereo PCM to MPV's stdin using a hysteresis buffer to keep memory strictly minimal (< 30 MB).
    """

    def __init__(
        self,
        tracks: List[Track],
        cache_manager: CacheManager,
        downloader: Downloader,
        light_mix: bool = False,
        crossfade_sec: float = DEFAULT_CROSSFADE_SEC,
        on_track_change: Optional[Callable[[int, Track, str], None]] = None,
        custom_socket: Optional[str] = None,
        start_idx: int = 0,
    ):
        self.tracks: List[Track] = list(tracks)
        self.cache_mgr = cache_manager
        self.downloader = downloader
        self.light_mix = light_mix
        self.crossfade_ms = int(crossfade_sec * 1000)
        self.fade_s = self.crossfade_ms / 1000.0
        self.on_track_change = on_track_change
        self.ipc_socket = custom_socket or self.cache_mgr.ipc_socket

        self.engine = DecisionEngine()
        self.playing_idx = max(0, min(start_idx, len(self.tracks) - 1)) if self.tracks else 0
        self.downloaded_idx = -1
        self._quit_flag = False
        self._lock = threading.Lock()

        self.last_transition: str = ""
        self.skip_to_next = False
        self.skip_to_prev = False
        self.jump_to_idx: Optional[int] = None
        self.toggle_pause = False

        self.mpv_process: Optional[subprocess.Popen] = None
        self.ipc: Optional[MPVIPCClient] = None

        # Precomputed transition cache: (from_idx, to_idx, overlap_chunk, eff_fade_ms, trans_type)
        self._precomputed_transition: Optional[Tuple[int, int, AudioSegment, int, str]] = None

        # Stream timeline mapping for accurate progress tracking
        # Each entry: {"idx": int, "track": Track, "stream_start_s": float, "duration": float, "transition": str}
        self.timeline: List[Dict[str, Any]] = []
        self.total_written_s = 0.0

    def start(self) -> threading.Thread:
        """Launch download prefetcher and audio streaming worker threads."""
        t_down = threading.Thread(target=self._download_worker, daemon=True, name="ytstr-dj-download")
        t_stream = threading.Thread(target=self._stream_worker, daemon=True, name="ytstr-dj-stream")

        t_down.start()
        t_stream.start()
        return t_stream

    def append_tracks(self, new_tracks: List[Track]) -> None:
        """Thread-safely append upcoming tracks (e.g. from radio generation)."""
        with self._lock:
            existing_ids = {t.id for t in self.tracks}
            for t in new_tracks:
                if t.id not in existing_ids:
                    self.tracks.append(t)
                    existing_ids.add(t.id)

    def jump_to(self, target_idx: int) -> None:
        """Jump playback immediately to target track index in queue without wiping tracks."""
        with self._lock:
            if 0 <= target_idx < len(self.tracks):
                self.jump_to_idx = target_idx

    def remove_track(self, index: int) -> bool:
        """Remove a future track from the upcoming playback queue."""
        with self._lock:
            if self.playing_idx < index < len(self.tracks):
                self.tracks.pop(index)
                return True
        return False

    def _launch_mpv(self) -> None:
        """Spawns an MPV instance listening for raw PCM over stdin."""
        if self.mpv_process:
            try:
                self.mpv_process.kill()
            except Exception:
                pass
        self.mpv_process = spawn_mpv_process(self.ipc_socket, raw_pcm_mode=True)
        self.ipc = MPVIPCClient(self.ipc_socket)

    def _download_worker(self) -> None:
        """
        Prefetches audio files for the active sliding window:
        Prioritizes current track, next two tracks, and previous track (< 30 MB).
        """
        while not self._quit_flag:
            with self._lock:
                total_tracks = len(self.tracks)
                curr_playing = self.playing_idx
                tracks_copy = list(self.tracks)

            if total_tracks == 0:
                time.sleep(0.4)
                continue

            # Target priority order:
            # 1. Currently playing
            # 2. Next track (curr_playing + 1)
            # 3. Next track + 2 (curr_playing + 2)
            # 4. Previous track (curr_playing - 1)
            targets = [curr_playing, curr_playing + 1, curr_playing + 2]
            if curr_playing > 0:
                targets.append(curr_playing - 1)

            downloaded_something = False
            for idx in targets:
                if self._quit_flag or self.jump_to_idx is not None:
                    break
                if 0 <= idx < total_tracks:
                    track = tracks_copy[idx]
                    if not self.cache_mgr.track_is_cached(track):
                        target_path = self.cache_mgr.get_track_cache_path(track, "opus")
                        self.downloader.download_track(track, target_path)
                        downloaded_something = True
                        break  # Yield loop to re-evaluate playing index

            # Prune cache to maintain strict bounded window
            self.cache_mgr.prune_window(curr_playing, tracks_copy)

            if not downloaded_something:
                time.sleep(0.35)

    def _precompute_transition_if_needed(self, curr_idx: int, curr_file: str, curr_dur_s: float) -> None:
        """Pre-compute the spectral crossfade before reaching track tail so boundary has zero delay."""
        next_idx = curr_idx + 1
        with self._lock:
            if next_idx >= len(self.tracks):
                return
            if self._precomputed_transition and self._precomputed_transition[0] == curr_idx:
                return
            next_track = self.tracks[next_idx]

        next_cached = self.cache_mgr.find_cached_file(next_track)
        if not next_cached or not next_cached.exists():
            return

        try:
            trans_type = TransitionType.FADE.value
            if not self.light_mix:
                # Analyze spectral frequencies of outgoing tail vs incoming head
                s_out = get_audio_chunk(curr_file, max(0.0, curr_dur_s - 5.0), 5.0)
                s_in = get_audio_chunk(str(next_cached), 0.0, 5.0)
                if len(s_out) > 0 and len(s_in) > 0:
                    trans_type = self.engine.select_transition(s_out, s_in)
                del s_out, s_in

            fade_chunk_out = get_audio_chunk(curr_file, max(0.0, curr_dur_s - self.fade_s), self.fade_s)
            fade_chunk_in = get_audio_chunk(str(next_cached), 0.0, self.fade_s)

            if len(fade_chunk_out) > 0 and len(fade_chunk_in) > 0:
                overlap, eff_fade = apply_transition(
                    trans_type, fade_chunk_out, fade_chunk_in, self.crossfade_ms
                )
                self._precomputed_transition = (curr_idx, next_idx, overlap, eff_fade, trans_type)
        except Exception as e:
            logger.debug("Error precomputing transition: %s", e)

    def _stream_worker(self) -> None:
        """
        Active audio streaming loop using Bounded Hysteresis:
        Pipes 6s raw PCM chunks into MPV until HIGH_WATERMARK (22s) is reached.
        Waits until MPV playback drains buffer below LOW_WATERMARK (8s) before resuming.
        """
        self._launch_mpv()
        with self._lock:
            curr_idx = self.playing_idx
        curr_time_s = 0.0
        pending_overlap: Optional[AudioSegment] = None

        while not self._quit_flag:
            with self._lock:
                total_tracks = len(self.tracks)

            if curr_idx >= total_tracks:
                time.sleep(0.5)
                continue

            # Process direct jump
            if self.jump_to_idx is not None:
                with self._lock:
                    curr_idx = self.jump_to_idx
                    self.jump_to_idx = None
                    self.playing_idx = curr_idx
                self._launch_mpv()
                curr_time_s = 0.0
                pending_overlap = None
                self._precomputed_transition = None
                self.timeline.clear()
                self.total_written_s = 0.0
                continue

            # Process user controls
            if self.skip_to_next:
                self.skip_to_next = False
                self._launch_mpv()
                curr_idx += 1
                curr_time_s = 0.0
                pending_overlap = None
                self._precomputed_transition = None
                self.timeline.clear()
                self.total_written_s = 0.0
                continue

            if self.skip_to_prev:
                self.skip_to_prev = False
                self._launch_mpv()
                curr_idx = max(0, curr_idx - 1)
                curr_time_s = 0.0
                pending_overlap = None
                self._precomputed_transition = None
                self.timeline.clear()
                self.total_written_s = 0.0
                continue

            if self.toggle_pause:
                self.toggle_pause = False
                if self.ipc:
                    self.ipc.cycle_pause()

            # Bounded Hysteresis backpressure control: check MPV playback time
            mpv_time_s = 0.0
            if self.ipc:
                try:
                    pt = self.ipc.get_property("playback-time")
                    if pt is not None:
                        mpv_time_s = float(pt)
                except Exception:
                    pass

            buffered_s = self.total_written_s - mpv_time_s
            if buffered_s > HIGH_WATERMARK_SEC:
                # Sleep briefly and check buffer until it drops below watermark
                time.sleep(0.25)
                continue

            with self._lock:
                is_last = (curr_idx == len(self.tracks) - 1)
                curr_track = self.tracks[curr_idx]

            # Wait for track file to become available in cache
            cached_file = self.cache_mgr.find_cached_file(curr_track)
            if not cached_file:
                time.sleep(0.15)
                continue

            file_path = str(cached_file)
            track_dur_s = get_audio_duration(file_path)
            if track_dur_s <= 0.0:
                time.sleep(0.15)
                continue

            end_limit_s = track_dur_s if is_last else max(0.0, track_dur_s - self.fade_s)
            remaining_s = end_limit_s - curr_time_s

            # Record track timeline entry for accurate progress & now-playing synchronization
            if not any(entry["idx"] == curr_idx for entry in self.timeline):
                self.timeline.append({
                    "idx": curr_idx,
                    "track": curr_track,
                    "stream_start_s": self.total_written_s,
                    "duration": track_dur_s,
                    "transition": self.last_transition,
                })

            # Check if MPV playback-time reached current track to update callbacks
            with self._lock:
                if self.playing_idx != curr_idx:
                    self.playing_idx = curr_idx
                    if self.on_track_change:
                        self.on_track_change(curr_idx, curr_track, self.last_transition)

            # Precompute upcoming transition when approaching tail (15s window)
            if not is_last and remaining_s <= 15.0:
                self._precompute_transition_if_needed(curr_idx, file_path, track_dur_s)

            chunk_dur_s = min(STREAM_CHUNK_SEC, remaining_s)

            if remaining_s > chunk_dur_s:
                chunk = get_audio_chunk(file_path, curr_time_s, chunk_dur_s)
                if pending_overlap is not None:
                    chunk = pending_overlap + chunk
                    pending_overlap = None

                self._write_pcm_to_mpv(chunk.raw_data)
                curr_time_s += chunk_dur_s
                self.total_written_s += len(chunk) / 1000.0
                del chunk
                gc.collect()
            else:
                # Reached track tail boundary
                if remaining_s > 0:
                    chunk = get_audio_chunk(file_path, curr_time_s, remaining_s)
                    if pending_overlap is not None:
                        chunk = pending_overlap + chunk
                        pending_overlap = None
                    self._write_pcm_to_mpv(chunk.raw_data)
                    self.total_written_s += len(chunk) / 1000.0
                    del chunk

                if not is_last:
                    # Retrieve precomputed transition or compute immediately
                    if (
                        not self._precomputed_transition
                        or self._precomputed_transition[0] != curr_idx
                    ):
                        with self._lock:
                            next_track_to_check = self.tracks[curr_idx + 1] if curr_idx + 1 < len(self.tracks) else None

                        # Ensure next track is ready
                        for _ in range(60):
                            if self._quit_flag or self.skip_to_next or self.skip_to_prev or self.jump_to_idx is not None:
                                break
                            if next_track_to_check and self.cache_mgr.track_is_cached(next_track_to_check):
                                break
                            time.sleep(0.1)

                        self._precompute_transition_if_needed(curr_idx, file_path, track_dur_s)

                    if self._quit_flag or self.skip_to_next or self.skip_to_prev or self.jump_to_idx is not None:
                        continue

                    if self._precomputed_transition and self._precomputed_transition[0] == curr_idx:
                        _, _, overlap, eff_fade, trans_type = self._precomputed_transition
                        self.last_transition = trans_type
                        self._precomputed_transition = None

                        # Write transition chunk seamlessly
                        self._write_pcm_to_mpv(overlap.raw_data)
                        self.total_written_s += len(overlap) / 1000.0
                        curr_time_s = eff_fade / 1000.0
                        del overlap
                    else:
                        curr_time_s = 0.0

                    gc.collect()

                # Notify cache manager that track finished
                with self._lock:
                    if curr_idx < len(self.tracks):
                        self.cache_mgr.on_track_finished(curr_idx, self.tracks[curr_idx])

                curr_idx += 1
                curr_time_s = 0.0
                gc.collect()

    def _write_pcm_to_mpv(self, raw_data: bytes) -> bool:
        """Write raw PCM byte buffer directly into MPV's stdin pipe."""
        if not self.mpv_process or not self.mpv_process.stdin:
            return False
        try:
            self.mpv_process.stdin.write(raw_data)
            self.mpv_process.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def get_playback_status(self) -> Dict[str, Any]:
        """
        Query current playback position and active track via MPV IPC.
        Safely falls back if properties are unparseable or mocked.
        """
        if not self.ipc:
            return {"now_playing": None, "time_pos": 0.0, "duration": 0.0, "paused": False}

        raw_pos = self.ipc.get_property("playback-time")
        mpv_time = 0.0
        if isinstance(raw_pos, (int, float)):
            mpv_time = float(raw_pos)
        elif isinstance(raw_pos, str):
            try:
                mpv_time = float(raw_pos)
            except ValueError:
                mpv_time = 0.0

        p = self.ipc.get_property("pause")
        is_paused = bool(p) if isinstance(p, bool) else False

        # Locate track in timeline matching current stream timestamp
        curr_track = None
        track_pos = 0.0
        track_dur = 0.0
        active_trans = ""

        with self._lock:
            for entry in reversed(self.timeline):
                if mpv_time >= entry["stream_start_s"]:
                    curr_track = entry["track"]
                    track_pos = max(0.0, mpv_time - entry["stream_start_s"])
                    track_dur = entry["duration"]
                    active_trans = entry["transition"]
                    self.playing_idx = entry["idx"]
                    break

            if not curr_track and self.tracks:
                curr_track = self.tracks[self.playing_idx] if self.playing_idx < len(self.tracks) else None

        return {
            "now_playing": curr_track.display_title() if curr_track else None,
            "track": curr_track,
            "time_pos": track_pos,
            "duration": track_dur,
            "paused": is_paused,
            "transition": active_trans,
            "playing_idx": self.playing_idx,
            "index": self.playing_idx,
        }

    def stop(self) -> None:
        """Cleanly tear down MPV subprocess, IPC client, and streaming threads."""
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
                if self.mpv_process.stdin:
                    self.mpv_process.stdin.close()
                self.mpv_process.terminate()
                self.mpv_process.wait(timeout=1.0)
            except Exception:
                try:
                    self.mpv_process.kill()
                except Exception:
                    pass
            self.mpv_process = None
