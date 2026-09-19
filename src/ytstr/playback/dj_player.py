"""
DJ streaming player engine with spectral handoff transitions, pydub mixing,
and bounded hysteresis streaming.
"""
import gc
import os
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple
from pydub import AudioSegment

from ytstr.audio.dsp import get_audio_chunk, get_audio_duration
from ytstr.audio.engine import DecisionEngine
from ytstr.audio.transitions import apply_transition
from ytstr.config import DEFAULT_CROSSFADE_SEC
from ytstr.core.types import Track, TransitionType
from ytstr.downloader.cache import CacheManager
from ytstr.downloader.ytdlp import Downloader
from ytstr.playback.mpv_ipc import MPVIPCClient, spawn_mpv_process

# Bounded Hysteresis Streaming Parameters
STREAM_CHUNK_SEC = 6.0       # Duration of each audio slice written to mpv
HIGH_WATERMARK_SEC = 22.0    # Maximum unplayed audio buffered ahead in MPV
LOW_WATERMARK_SEC = 8.0      # Resume writing when buffer drops below this threshold


class DJPlayer:
    """
    Audio player pipeline that dynamically crossfades overlapping track boundaries
    using DSP transitions and streams raw 16-bit 44.1kHz stereo PCM into mpv's stdin
    using a strictly bounded hysteresis buffer (< 30 MB peak RAM).
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
        self.playing_idx = 0
        self.downloaded_idx = -1
        self._quit_flag = False
        self._lock = threading.Lock()

        self.last_transition: str = ""
        self.skip_to_next = False
        self.skip_to_prev = False
        self.toggle_pause = False

        self.mpv_process: Optional[subprocess.Popen] = None
        self.ipc: Optional[MPVIPCClient] = None

        # Precomputed transition cache: (from_idx, to_idx) -> (overlap_chunk, eff_fade_ms, trans_type)
        self._precomputed_transition: Optional[Tuple[int, int, AudioSegment, int, str]] = None

        # Stream timeline mapping for accurate progress tracking
        # Each entry: {"idx": int, "track": Track, "stream_start_s": float, "stream_end_s": float, "duration": float, "transition": str}
        self.timeline: List[Dict] = []
        self.total_written_s = 0.0

    def start(self):
        """Launch download prefetcher and audio streaming worker threads."""
        t_down = threading.Thread(target=self._download_worker, daemon=True, name="ytstr-dj-download")
        t_stream = threading.Thread(target=self._stream_worker, daemon=True, name="ytstr-dj-stream")

        t_down.start()
        t_stream.start()
        return t_stream

    def append_tracks(self, new_tracks: List[Track]):
        """Thread-safely append upcoming tracks (e.g. from radio generation)."""
        with self._lock:
            existing_ids = {t.id for t in self.tracks}
            for t in new_tracks:
                if t.id not in existing_ids:
                    self.tracks.append(t)
                    existing_ids.add(t.id)

    def remove_track(self, index: int) -> bool:
        """Remove a future track from the upcoming playback queue."""
        with self._lock:
            if index > self.playing_idx and index < len(self.tracks):
                self.tracks.pop(index)
                return True
        return False

    def _launch_mpv(self):
        """Spawns an MPV instance listening for raw PCM over stdin."""
        if self.mpv_process:
            try:
                self.mpv_process.kill()
            except Exception:
                pass
        self.mpv_process = spawn_mpv_process(self.ipc_socket, raw_pcm_mode=True)
        self.ipc = MPVIPCClient(self.ipc_socket)

    def _download_worker(self):
        """Prefetches audio files up to 2 tracks ahead onto disk in the background."""
        while not self._quit_flag:
            with self._lock:
                total_tracks = len(self.tracks)
                curr_playing = self.playing_idx

            if self.downloaded_idx < total_tracks - 1:
                # Keep downloaded index at least 2 tracks ahead of currently playing track
                if self.downloaded_idx <= curr_playing + 1:
                    target_idx = self.downloaded_idx + 1
                    with self._lock:
                        if target_idx < len(self.tracks):
                            track = self.tracks[target_idx]
                        else:
                            track = None

                    if track:
                        target_path = self.cache_mgr.get_track_cache_path(target_idx, "opus")
                        if not self.cache_mgr.track_is_cached(target_idx):
                            self.downloader.download_track(track, target_path)

                        self.downloaded_idx = target_idx
                else:
                    time.sleep(0.3)
            else:
                time.sleep(0.5)

    def _precompute_transition_if_needed(self, curr_idx: int, curr_file: str, curr_dur_s: float):
        """Pre-compute the spectral crossfade before reaching track tail so boundary has zero delay."""
        next_idx = curr_idx + 1
        with self._lock:
            if next_idx >= len(self.tracks):
                return
            if self._precomputed_transition and self._precomputed_transition[0] == curr_idx:
                return

        next_cached = self.cache_mgr.find_cached_file(next_idx)
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
            del fade_chunk_out, fade_chunk_in
        except Exception:
            pass

    def _stream_worker(self):
        """Main audio processing and hysteresis streaming loop."""
        # Wait for first track to start downloading
        while self.downloaded_idx < 0 and not self._quit_flag:
            time.sleep(0.1)
        if self._quit_flag:
            return

        self._launch_mpv()

        curr_idx = 0
        curr_time_s = 0.0
        self.total_written_s = 0.0
        pending_overlap: Optional[AudioSegment] = None

        while not self._quit_flag:
            with self._lock:
                if curr_idx >= len(self.tracks):
                    # End of queue, idle wait for more tracks or exit
                    time.sleep(0.3)
                    continue

            # Handle user skip forward
            if self.skip_to_next:
                self.skip_to_next = False
                with self._lock:
                    self.cache_mgr.on_track_finished(curr_idx, self.tracks[curr_idx])
                    curr_idx += 1
                curr_time_s = 0.0
                pending_overlap = None
                self._precomputed_transition = None
                self._launch_mpv()
                self.total_written_s = 0.0
                self.timeline.clear()
                continue

            # Handle user skip backward
            if self.skip_to_prev:
                self.skip_to_prev = False
                with self._lock:
                    curr_idx = max(0, curr_idx - 1)
                curr_time_s = 0.0
                pending_overlap = None
                self._precomputed_transition = None
                self._launch_mpv()
                self.total_written_s = 0.0
                self.timeline.clear()
                continue

            # Handle pause toggle
            if self.toggle_pause:
                self.toggle_pause = False
                if self.ipc:
                    self.ipc.cycle_pause()

            # Bounded Hysteresis: throttle if MPV buffer is > HIGH_WATERMARK_SEC ahead
            mpv_time_s = 0.0
            if self.ipc:
                playback_val = self.ipc.get_property("playback-time")
                if playback_val is not None:
                    try:
                        mpv_time_s = float(playback_val)
                    except (ValueError, TypeError):
                        pass

            buffered_s = self.total_written_s - mpv_time_s
            if buffered_s > HIGH_WATERMARK_SEC:
                # Sleep briefly and check buffer until it drops below watermark
                time.sleep(0.25)
                continue

            # Wait for file to become available
            if self.downloaded_idx < curr_idx:
                time.sleep(0.2)
                continue

            cached_file = self.cache_mgr.find_cached_file(curr_idx)
            if not cached_file:
                time.sleep(0.2)
                continue

            file_path = str(cached_file)
            track_dur_s = get_audio_duration(file_path)
            if track_dur_s <= 0.0:
                time.sleep(0.2)
                continue

            with self._lock:
                is_last = curr_idx == len(self.tracks) - 1
                curr_track = self.tracks[curr_idx]

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
                elif pending_overlap is not None:
                    self._write_pcm_to_mpv(pending_overlap.raw_data)
                    self.total_written_s += len(pending_overlap) / 1000.0
                    pending_overlap = None

                # Perform seamless transition into next track without silence
                if not is_last:
                    # Retrieve precomputed transition or compute immediately
                    if (
                        not self._precomputed_transition
                        or self._precomputed_transition[0] != curr_idx
                    ):
                        # Ensure next track is ready
                        for _ in range(60):
                            if self._quit_flag or self.skip_to_next or self.skip_to_prev:
                                break
                            if self.downloaded_idx >= curr_idx + 1:
                                break
                            time.sleep(0.1)

                        self._precompute_transition_if_needed(curr_idx, file_path, track_dur_s)

                    if self._quit_flag or self.skip_to_next or self.skip_to_prev:
                        continue

                    if self._precomputed_transition and self._precomputed_transition[0] == curr_idx:
                        _, next_i, overlap, eff_fade, trans_type = self._precomputed_transition
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
                self.cache_mgr.prune_earlier_than(curr_idx)

                curr_idx += 1

    def _write_pcm_to_mpv(self, raw_bytes: bytes):
        """Safely write PCM bytes to mpv stdin with backpressure guard."""
        if not self.mpv_process or not self.mpv_process.stdin:
            return
        try:
            self.mpv_process.stdin.write(raw_bytes)
            self.mpv_process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def get_playback_status(self) -> Dict:
        """
        Query current playback position mapped to current track timeline.
        Returns:
            dict containing: {
                'index': int,
                'track': Optional[Track],
                'time_pos': float,
                'duration': float,
                'is_paused': bool,
                'transition': str
            }
        """
        if not self.ipc:
            return {"index": self.playing_idx, "track": None, "time_pos": 0.0, "duration": 0.0, "is_paused": False, "transition": ""}

        mpv_time_s = 0.0
        is_paused = False
        try:
            pt = self.ipc.get_property("playback-time")
            if pt is not None:
                mpv_time_s = float(pt)
            p = self.ipc.get_property("pause")
            if p is not None:
                is_paused = bool(p)
        except Exception:
            pass

        # Locate which track interval mpv_time_s is currently playing
        active_entry = None
        for entry in self.timeline:
            start_s = entry["stream_start_s"]
            end_s = start_s + entry["duration"]
            if start_s <= mpv_time_s < end_s:
                active_entry = entry
                break

        if not active_entry and self.timeline:
            active_entry = self.timeline[-1]

        if active_entry:
            elapsed = max(0.0, mpv_time_s - active_entry["stream_start_s"])
            return {
                "index": active_entry["idx"],
                "track": active_entry["track"],
                "time_pos": min(active_entry["duration"], elapsed),
                "duration": active_entry["duration"],
                "is_paused": is_paused,
                "transition": active_entry.get("transition", ""),
            }

        with self._lock:
            curr_track = self.tracks[self.playing_idx] if self.playing_idx < len(self.tracks) else None
        return {
            "index": self.playing_idx,
            "track": curr_track,
            "time_pos": 0.0,
            "duration": curr_track.duration_sec if curr_track else 0.0,
            "is_paused": is_paused,
            "transition": self.last_transition,
        }

    def stop(self):
        """Terminate mpv and cleanup workers."""
        self._quit_flag = True
        if self.mpv_process:
            try:
                self.mpv_process.kill()
            except Exception:
                pass
            self.mpv_process = None
