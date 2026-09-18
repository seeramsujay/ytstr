"""
DJ streaming player engine with spectral handoff transitions and pydub mixing.
"""
import gc
import os
import subprocess
import threading
import time
from typing import Callable, List, Optional
from pydub import AudioSegment

from ytstr.audio.dsp import get_audio_chunk, get_audio_duration
from ytstr.audio.engine import DecisionEngine
from ytstr.audio.transitions import apply_transition
from ytstr.config import CHUNK_DURATION_SEC, DEFAULT_CROSSFADE_SEC, MAX_BUFFER_AHEAD_SEC
from ytstr.core.types import Track, TransitionType
from ytstr.downloader.cache import CacheManager
from ytstr.downloader.ytdlp import Downloader
from ytstr.playback.mpv_ipc import MPVIPCClient, spawn_mpv_process


class DJPlayer:
    """
    Audio player pipeline that dynamically crossfades overlapping track boundaries
    using DSP transitions and writes raw 16-bit 44.1kHz PCM to mpv's stdin.
    """

    def __init__(
        self,
        tracks: List[Track],
        cache_manager: CacheManager,
        downloader: Downloader,
        light_mix: bool = False,
        crossfade_sec: float = DEFAULT_CROSSFADE_SEC,
        on_track_change: Optional[Callable[[int, Track, str], None]] = None,
    ):
        self.tracks = tracks
        self.cache_mgr = cache_manager
        self.downloader = downloader
        self.light_mix = light_mix
        self.crossfade_ms = int(crossfade_sec * 1000)
        self.on_track_change = on_track_change

        self.engine = DecisionEngine()
        self.playing_idx = 0
        self.downloaded_idx = -1
        self._quit_flag = False

        self.last_transition: str = ""
        self.skip_to_next = False
        self.skip_to_prev = False
        self.toggle_pause = False

        self.mpv_process: Optional[subprocess.Popen] = None
        self.ipc: Optional[MPVIPCClient] = None

    def start(self):
        """Launch worker threads."""
        t_down = threading.Thread(target=self._download_worker, daemon=True)
        t_stream = threading.Thread(target=self._stream_worker, daemon=True)

        t_down.start()
        t_stream.start()
        return t_stream

    def _launch_mpv(self):
        """Spawns an MPV instance listening for raw PCM over stdin."""
        if self.mpv_process:
            try:
                self.mpv_process.kill()
            except Exception:
                pass
        self.mpv_process = spawn_mpv_process(self.cache_mgr.ipc_socket, raw_pcm_mode=True)
        self.ipc = MPVIPCClient(self.cache_mgr.ipc_socket)

    def _download_worker(self):
        """Prefetches audio files up to 2 tracks ahead on disk."""
        while not self._quit_flag and self.downloaded_idx < len(self.tracks) - 1:
            if self.downloaded_idx <= self.playing_idx + 1:
                target_idx = self.downloaded_idx + 1
                track = self.tracks[target_idx]
                target_path = self.cache_mgr.get_track_cache_path(target_idx, "opus")

                if not self.cache_mgr.track_is_cached(target_idx):
                    self.downloader.download_track(track, target_path)

                self.downloaded_idx = target_idx
            else:
                time.sleep(0.5)

    def _stream_worker(self):
        """Main audio processing and streaming loop."""
        # Wait for first track to start downloading
        while self.downloaded_idx < 0 and not self._quit_flag:
            time.sleep(0.3)
        if self._quit_flag:
            return

        self._launch_mpv()

        curr_idx = 0
        curr_time_s = 0.0
        total_written_s = 0.0
        pending_overlap: Optional[AudioSegment] = None

        while not self._quit_flag and curr_idx < len(self.tracks):
            # Handle user navigation controls
            if self.skip_to_next:
                self.skip_to_next = False
                self.cache_mgr.on_track_finished(curr_idx, self.tracks[curr_idx])
                curr_idx += 1
                curr_time_s = 0.0
                total_written_s = 0.0
                pending_overlap = None
                self._launch_mpv()
                if curr_idx >= len(self.tracks):
                    break
                continue

            if self.skip_to_prev:
                self.skip_to_prev = False
                curr_idx = max(0, curr_idx - 1)
                curr_time_s = 0.0
                total_written_s = 0.0
                pending_overlap = None
                self._launch_mpv()
                continue

            if self.toggle_pause:
                self.toggle_pause = False
                if self.ipc:
                    self.ipc.cycle_pause()

            # Buffer Hysteresis: throttle if mpv buffer is > MAX_BUFFER_AHEAD_SEC ahead
            mpv_time_s = 0.0
            if self.ipc:
                playback_val = self.ipc.get_property("playback-time")
                if playback_val is not None:
                    try:
                        mpv_time_s = float(playback_val)
                    except (ValueError, TypeError):
                        pass

            buffered_s = total_written_s - mpv_time_s
            if buffered_s > MAX_BUFFER_AHEAD_SEC:
                time.sleep(0.5)
                continue

            # Wait for file to become available
            if self.downloaded_idx < curr_idx:
                time.sleep(0.4)
                continue

            cached_file = self.cache_mgr.find_cached_file(curr_idx)
            if not cached_file:
                time.sleep(0.4)
                continue

            track_dur_s = get_audio_duration(str(cached_file))
            if track_dur_s <= 0.0:
                time.sleep(0.4)
                continue

            fade_s = self.crossfade_ms / 1000.0
            is_last = curr_idx == len(self.tracks) - 1
            end_limit_s = track_dur_s if is_last else (track_dur_s - fade_s)
            remaining_s = end_limit_s - curr_time_s

            if self.playing_idx != curr_idx:
                self.playing_idx = curr_idx
                if self.on_track_change:
                    self.on_track_change(curr_idx, self.tracks[curr_idx], self.last_transition)

            chunk_dur_s = min(CHUNK_DURATION_SEC, remaining_s)

            if remaining_s > chunk_dur_s:
                chunk = get_audio_chunk(str(cached_file), curr_time_s, chunk_dur_s)
                if pending_overlap is not None:
                    chunk = pending_overlap + chunk
                    pending_overlap = None

                self._write_pcm_to_mpv(chunk.raw_data)
                curr_time_s += chunk_dur_s
                total_written_s += len(chunk) / 1000.0
                del chunk
                gc.collect()
            else:
                # Reached track tail boundary
                if remaining_s > 0:
                    chunk = get_audio_chunk(str(cached_file), curr_time_s, remaining_s)
                    if pending_overlap is not None:
                        chunk = pending_overlap + chunk
                        pending_overlap = None
                    self._write_pcm_to_mpv(chunk.raw_data)
                    total_written_s += len(chunk) / 1000.0
                    del chunk
                elif pending_overlap is not None:
                    self._write_pcm_to_mpv(pending_overlap.raw_data)
                    total_written_s += len(pending_overlap) / 1000.0
                    pending_overlap = None

                # Compute DJ crossfade into next track
                if not is_last:
                    # Wait for next track to download
                    while (
                        self.downloaded_idx < curr_idx + 1
                        and not self._quit_flag
                        and not self.skip_to_next
                        and not self.skip_to_prev
                    ):
                        time.sleep(0.3)

                    if self._quit_flag or self.skip_to_next or self.skip_to_prev:
                        continue

                    next_cached = self.cache_mgr.find_cached_file(curr_idx + 1)
                    if next_cached:
                        trans_type = TransitionType.FADE.value
                        if not self.light_mix:
                            s_out = get_audio_chunk(str(cached_file), track_dur_s - 5.0, 5.0)
                            s_in = get_audio_chunk(str(next_cached), 0.0, 5.0)
                            trans_type = self.engine.select_transition(s_out, s_in)
                            del s_out, s_in

                        self.last_transition = trans_type

                        fade_chunk_out = get_audio_chunk(str(cached_file), track_dur_s - fade_s, fade_s)
                        fade_chunk_in = get_audio_chunk(str(next_cached), 0.0, fade_s)

                        overlap, eff_fade = apply_transition(
                            trans_type, fade_chunk_out, fade_chunk_in, self.crossfade_ms
                        )
                        del fade_chunk_out, fade_chunk_in

                        half_fade = eff_fade // 2
                        if eff_fade > 0:
                            out_chunk = overlap[:half_fade]
                            pending_overlap = overlap[half_fade:]
                            curr_time_s = eff_fade / 1000.0
                        else:
                            out_chunk = AudioSegment.empty()
                            curr_time_s = 0.0

                        if len(out_chunk) > 0:
                            self._write_pcm_to_mpv(out_chunk.raw_data)
                            total_written_s += len(out_chunk) / 1000.0
                            del out_chunk

                        del overlap
                        gc.collect()

                # Notify cache manager that track finished
                self.cache_mgr.on_track_finished(curr_idx, self.tracks[curr_idx])
                self.cache_mgr.prune_earlier_than(curr_idx)

                curr_idx += 1

    def _write_pcm_to_mpv(self, raw_bytes: bytes):
        """Safely write PCM bytes to mpv stdin."""
        if not self.mpv_process or not self.mpv_process.stdin:
            return
        try:
            self.mpv_process.stdin.write(raw_bytes)
            self.mpv_process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def stop(self):
        """Terminate mpv and cleanup workers."""
        self._quit_flag = True
        if self.mpv_process:
            try:
                self.mpv_process.kill()
            except Exception:
                pass
