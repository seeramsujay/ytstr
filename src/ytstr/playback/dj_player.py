"""
Auto-DJ and Light-Mix audio player streaming raw PCM over stdin to MPV via Bounded Hysteresis.

Mixing modes are strictly separated:
- Light Mix: every boundary is a plain equal-power crossfade of `crossfade_sec`;
  no spectral analysis ever runs.
- Auto-DJ: the outgoing tail and incoming head are analysed and one of the 8
  psychoacoustic transitions is rendered at its natural length.

Transitions are rendered on a background thread well before the boundary, so the
streaming thread never blocks on DSP. Track changes and transitions are announced
when they become audible, not when they are written ahead into mpv's buffer.
"""
from __future__ import annotations

import gc
import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from pydub import AudioSegment

from ytstr.audio.dsp import get_audio_chunk, get_audio_duration
from ytstr.audio.engine import DecisionEngine
from ytstr.audio.transitions import apply_transition, max_transition_window_ms, transition_window_ms
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

# Start rendering the next transition when this close to the outgoing track's mix point
MIX_RENDER_LEAD_SEC = 30.0
# At a boundary, wait for a pending mix render / next download at most this long...
BOUNDARY_WAIT_SEC = 6.0
# ...and never let mpv's buffer drop below this while waiting (prevents audible gaps)
MIN_BUFFER_WHILE_WAITING_SEC = 1.5
# Spectral analysis window (outgoing tail / incoming head) for Auto-DJ decisions
ANALYSIS_SEC = 5.0
# Timeline entries kept for position mapping (older ones are long inaudible)
MAX_TIMELINE_ENTRIES = 8

MODE_LIGHT_MIX = "Light Mix"
MODE_AUTO_DJ = "Auto-DJ"


@dataclass
class PlannedMix:
    """A transition rendered ahead of time for the boundary after `from_idx`."""
    from_idx: int
    to_track_id: str
    light_mix: bool
    trans_type: str
    overlap: AudioSegment
    consumed_ms: int  # ms used from both the outgoing tail and the incoming head


class DJPlayer:
    """
    Manages continuous seamless audio playback with psychoacoustic transitions.
    Decodes audio into memory only in bounded chunks, streaming raw 16-bit 44.1kHz
    stereo PCM to MPV's stdin using a hysteresis buffer to keep memory strictly minimal.
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

        # Background transition rendering
        self._mix_lock = threading.Lock()
        self._mix_gen = 0
        self._planned_mix: Optional[PlannedMix] = None
        self._render_thread: Optional[threading.Thread] = None
        self._light_mix = bool(light_mix)
        # False = finish tracks unmixed (e.g. while handing over to a direct mode)
        self._mix_enabled = True

        # Index of the track currently being written into mpv (may be ahead of audible)
        self._stream_idx = self.playing_idx
        self._announced_key: Optional[tuple] = None

        # Stream timeline mapping for accurate progress tracking. Each entry:
        # {"idx", "track", "stream_start_s", "duration", "transition", "mix_end_s"}
        self.timeline: List[Dict[str, Any]] = []
        self.total_written_s = 0.0

    # ------------------------------------------------------------------
    # Mode handling
    # ------------------------------------------------------------------
    @property
    def light_mix(self) -> bool:
        return self._light_mix

    @light_mix.setter
    def light_mix(self, value: bool) -> None:
        """Switch Light Mix / Auto-DJ; the next boundary is re-rendered in the new mode."""
        value = bool(value)
        if value != self._light_mix:
            self._light_mix = value
            self._invalidate_mix()

    @property
    def mix_enabled(self) -> bool:
        return self._mix_enabled

    @mix_enabled.setter
    def mix_enabled(self, value: bool) -> None:
        value = bool(value)
        if value != self._mix_enabled:
            self._mix_enabled = value
            self._invalidate_mix()

    @property
    def mode_label(self) -> str:
        return MODE_LIGHT_MIX if self._light_mix else MODE_AUTO_DJ

    def _tail_reserve_ms(self) -> int:
        """Audio held back at each track's end for the mix (depends on the mode)."""
        if not self._mix_enabled:
            return 0
        if self._light_mix:
            return self.crossfade_ms
        return max_transition_window_ms(self.crossfade_ms)

    def _invalidate_mix(self) -> None:
        with self._mix_lock:
            self._mix_gen += 1
            self._planned_mix = None

    # ------------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------------
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
        """
        Remove a future track from the upcoming playback queue.

        Tracks already written into mpv's buffer (the audible track, or the next
        track once its crossfade has been streamed) cannot be removed this way.
        """
        with self._lock:
            if max(self.playing_idx, self._stream_idx) < index < len(self.tracks):
                self.tracks.pop(index)
                if self._planned_mix and self._planned_mix.from_idx == index - 1:
                    self._invalidate_mix()
                return True
        return False

    def remove_current_track(self, index: int) -> bool:
        """Remove the audible track at index and continue with the track that follows it."""
        with self._lock:
            if not 0 <= index < len(self.tracks):
                return False
            self.tracks.pop(index)
            # The following track has shifted into this slot; restart the stream there
            self.jump_to_idx = min(index, len(self.tracks))
            return True

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------
    def _launch_mpv(self) -> None:
        """Spawns an MPV instance listening for raw PCM over stdin."""
        if self.ipc:
            self.ipc.close()
        if self.mpv_process:
            try:
                self.mpv_process.kill()
                self.mpv_process.wait(timeout=1.0)
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
                    if self.cache_mgr.download_if_needed(tracks_copy[idx], self.downloader):
                        downloaded_something = True
                        break  # Yield loop to re-evaluate playing index

            # Prune cache to maintain strict bounded window
            self.cache_mgr.prune_window(curr_playing, tracks_copy)

            if not downloaded_something:
                time.sleep(0.35)

    def _start_mix_render(self, curr_idx: int, curr_file: str, curr_dur_s: float, max_out_ms: int) -> None:
        """Render the transition into the next track on a background thread (if not already)."""
        if not self._mix_enabled:
            return
        with self._lock:
            if curr_idx + 1 >= len(self.tracks):
                return
            next_track = self.tracks[curr_idx + 1]
        light = self._light_mix

        with self._mix_lock:
            planned = self._planned_mix
            if planned and planned.from_idx == curr_idx and planned.to_track_id == next_track.id \
                    and planned.light_mix == light:
                return
            if self._render_thread and self._render_thread.is_alive():
                return
            next_file = self.cache_mgr.find_cached_file(next_track)
            if not next_file or not next_file.exists() or max_out_ms <= 0:
                return
            gen = self._mix_gen
            self._render_thread = threading.Thread(
                target=self._render_mix,
                args=(gen, curr_idx, curr_file, curr_dur_s, next_track, str(next_file), light, max_out_ms),
                daemon=True,
                name="ytstr-dj-render",
            )
            self._render_thread.start()

    def _render_mix(
        self,
        gen: int,
        curr_idx: int,
        curr_file: str,
        curr_dur_s: float,
        next_track: Track,
        next_file: str,
        light: bool,
        max_out_ms: int,
    ) -> None:
        """Select (Auto-DJ only) and render the transition overlap between two tracks."""
        try:
            if light:
                # Light Mix: fixed equal-power crossfade, never any spectral analysis
                trans_type = TransitionType.FADE.value
            else:
                s_out = get_audio_chunk(curr_file, max(0.0, curr_dur_s - ANALYSIS_SEC), ANALYSIS_SEC)
                s_in = get_audio_chunk(next_file, 0.0, ANALYSIS_SEC)
                trans_type = TransitionType.FADE.value
                if len(s_out) > 0 and len(s_in) > 0:
                    trans_type = self.engine.select_transition(s_out, s_in)
                del s_out, s_in

            window_ms = min(transition_window_ms(trans_type, self.crossfade_ms), max_out_ms)
            window_s = window_ms / 1000.0
            fade_out = get_audio_chunk(curr_file, max(0.0, curr_dur_s - window_s), window_s)
            fade_in = get_audio_chunk(next_file, 0.0, window_s)
            if len(fade_out) == 0 or len(fade_in) == 0:
                return

            overlap, consumed_ms = apply_transition(trans_type, fade_out, fade_in, self.crossfade_ms)
            del fade_out, fade_in
            if consumed_ms <= 0 or len(overlap) == 0:
                return

            with self._mix_lock:
                if gen == self._mix_gen and not self._quit_flag:
                    self._planned_mix = PlannedMix(
                        from_idx=curr_idx,
                        to_track_id=next_track.id,
                        light_mix=light,
                        trans_type=trans_type,
                        overlap=overlap,
                        consumed_ms=consumed_ms,
                    )
        except Exception as e:
            logger.debug("Error rendering transition: %s", e)

    def _take_planned_mix(self, curr_idx: int, next_track: Track, unwritten_ms: int) -> Optional[PlannedMix]:
        """Return the rendered mix for this boundary if it still matches the queue and mode."""
        with self._mix_lock:
            mix = self._planned_mix
            if (
                mix
                and mix.from_idx == curr_idx
                and mix.to_track_id == next_track.id
                and mix.light_mix == self._light_mix
                and mix.consumed_ms <= unwritten_ms
            ):
                self._planned_mix = None
                return mix
            return None

    def _mpv_time(self) -> float:
        """Seconds of the PCM stream mpv has played so far (0.0 if unknown)."""
        if not self.ipc:
            return 0.0
        try:
            pt = self.ipc.get_property("playback-time")
            return float(pt) if isinstance(pt, (int, float)) else 0.0
        except Exception:
            return 0.0

    def _buffered_s(self) -> float:
        return self.total_written_s - self._mpv_time()

    def _audible_entry(self, mpv_time: float) -> Optional[Dict[str, Any]]:
        """Timeline entry playing at stream time mpv_time. Caller holds self._lock."""
        for entry in reversed(self.timeline):
            if mpv_time >= entry["stream_start_s"]:
                return entry
        return None

    def _announce_audible(self, mpv_time: float) -> None:
        """Fire on_track_change once per track, at the moment it becomes audible."""
        with self._lock:
            entry = self._audible_entry(mpv_time)
            if entry is None:
                return
            key = (entry["idx"], entry["track"].id)
            if key == self._announced_key:
                return
            self._announced_key = key
            self.playing_idx = entry["idx"]
        if self.on_track_change:
            self.on_track_change(entry["idx"], entry["track"], entry["transition"])

    def _add_timeline_entry(self, idx: int, track: Track, duration: float, transition: str, mix_len_s: float) -> None:
        with self._lock:
            self.timeline.append({
                "idx": idx,
                "track": track,
                "stream_start_s": self.total_written_s,
                "duration": duration,
                "transition": transition,
                "mix_end_s": self.total_written_s + mix_len_s,
            })
            del self.timeline[:-MAX_TIMELINE_ENTRIES]

    def _write_segment(self, audio: AudioSegment) -> None:
        self._write_pcm_to_mpv(audio.raw_data)
        self.total_written_s += len(audio) / 1000.0

    def _restart_stream(self) -> None:
        """Fresh mpv instance and timeline after a jump / skip."""
        self._launch_mpv()
        self._invalidate_mix()
        with self._lock:
            self.timeline.clear()
            self._announced_key = None
        self.total_written_s = 0.0

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
        draining = False  # Hysteresis state: True after HIGH_WATERMARK until LOW_WATERMARK

        while not self._quit_flag:
            # Process direct jump and user controls
            if self.jump_to_idx is not None:
                with self._lock:
                    curr_idx = self.jump_to_idx
                    self.jump_to_idx = None
                    self.playing_idx = curr_idx
                self._restart_stream()
                curr_time_s = 0.0
                continue

            if self.skip_to_next or self.skip_to_prev:
                with self._lock:
                    if self.skip_to_next:
                        curr_idx = min(curr_idx + 1, len(self.tracks))
                    else:
                        curr_idx = max(0, curr_idx - 1)
                    self.skip_to_next = self.skip_to_prev = False
                self._restart_stream()
                curr_time_s = 0.0
                continue

            if self.toggle_pause:
                self.toggle_pause = False
                if self.ipc:
                    self.ipc.cycle_pause()

            mpv_time_s = self._mpv_time()
            self._announce_audible(mpv_time_s)

            with self._lock:
                total_tracks = len(self.tracks)
                self._stream_idx = curr_idx

            if curr_idx >= total_tracks:
                # End of queue: idle until radio appends tracks or the user jumps back
                time.sleep(0.25)
                continue

            # Bounded hysteresis backpressure on mpv's buffered audio
            buffered_s = self.total_written_s - mpv_time_s
            if buffered_s > HIGH_WATERMARK_SEC:
                draining = True
            elif buffered_s < LOW_WATERMARK_SEC:
                draining = False
            if draining:
                time.sleep(0.25)
                continue

            with self._lock:
                is_last = (curr_idx == len(self.tracks) - 1)
                curr_track = self.tracks[curr_idx]

            # Wait for track file to become available in cache
            cached_file = self.cache_mgr.find_cached_file(curr_track)
            if not cached_file:
                if self.cache_mgr.is_unavailable(curr_track):
                    # Download repeatedly failed: skip the unplayable track
                    curr_idx += 1
                    curr_time_s = 0.0
                    continue
                time.sleep(0.15)
                continue

            file_path = str(cached_file)
            track_dur_s = get_audio_duration(file_path)
            if track_dur_s <= 0.0:
                time.sleep(0.15)
                continue

            with self._lock:
                has_entry = any(e["idx"] == curr_idx and e["track"].id == curr_track.id for e in self.timeline)
            if not has_entry:
                self._add_timeline_entry(curr_idx, curr_track, track_dur_s, "", 0.0)

            # Stream the body up to the mix point (the whole track if nothing follows)
            reserve_s = 0.0 if is_last else self._tail_reserve_ms() / 1000.0
            mix_point_s = max(curr_time_s, track_dur_s - reserve_s)

            if not is_last and mix_point_s - curr_time_s <= MIX_RENDER_LEAD_SEC:
                unwritten_ms = int((track_dur_s - mix_point_s) * 1000)
                self._start_mix_render(curr_idx, file_path, track_dur_s, unwritten_ms)

            if mix_point_s - curr_time_s > 0.001:
                chunk_s = min(STREAM_CHUNK_SEC, mix_point_s - curr_time_s)
                chunk = get_audio_chunk(file_path, curr_time_s, chunk_s)
                self._write_segment(chunk)
                curr_time_s += chunk_s
                del chunk
                gc.collect()
                continue

            # Reached the mix point: hand over to the next track
            next_start_s = self._finish_track(curr_idx, curr_track, file_path, track_dur_s, curr_time_s, is_last)
            if next_start_s is None:
                continue  # Interrupted by a user control; handled at the top of the loop

            with self._lock:
                if curr_idx < len(self.tracks):
                    self.cache_mgr.on_track_finished(curr_idx, self.tracks[curr_idx])
            curr_idx += 1
            curr_time_s = next_start_s
            gc.collect()

    def _controls_pending(self) -> bool:
        return self._quit_flag or self.skip_to_next or self.skip_to_prev or self.jump_to_idx is not None

    def _finish_track(
        self,
        curr_idx: int,
        curr_track: Track,
        file_path: str,
        track_dur_s: float,
        curr_time_s: float,
        is_last: bool,
    ) -> Optional[float]:
        """
        Write the remainder of the outgoing track, mixed into the next one if possible.

        Returns:
            Offset (s) at which the next track's body resumes, or None if interrupted.
        """
        unwritten_ms = int(max(0.0, track_dur_s - curr_time_s) * 1000)
        with self._lock:
            next_track = None if is_last or curr_idx + 1 >= len(self.tracks) else self.tracks[curr_idx + 1]

        mix: Optional[PlannedMix] = None
        if next_track is not None and self._mix_enabled:
            # Give a pending download / render a moment, but never drain mpv's buffer dry
            deadline = time.monotonic() + BOUNDARY_WAIT_SEC
            while not self._controls_pending():
                mix = self._take_planned_mix(curr_idx, next_track, unwritten_ms)
                if mix is not None or self.cache_mgr.is_unavailable(next_track):
                    break
                self._start_mix_render(curr_idx, file_path, track_dur_s, unwritten_ms)
                if time.monotonic() > deadline or self._buffered_s() < MIN_BUFFER_WHILE_WAITING_SEC:
                    break
                self._announce_audible(self._mpv_time())
                time.sleep(0.1)
            if self._controls_pending():
                return None

        if mix is None:
            # No mix available: play the outgoing track to its very end, then a clean start
            if unwritten_ms > 0:
                self._write_segment(get_audio_chunk(file_path, curr_time_s, unwritten_ms / 1000.0))
            self.last_transition = ""
            return 0.0

        # Outgoing body up to where the overlap begins, then the rendered overlap
        mix_start_s = track_dur_s - mix.consumed_ms / 1000.0
        if mix_start_s - curr_time_s > 0.001:
            self._write_segment(get_audio_chunk(file_path, curr_time_s, mix_start_s - curr_time_s))

        assert next_track is not None
        next_cached = self.cache_mgr.find_cached_file(next_track)
        next_dur_s = get_audio_duration(str(next_cached)) if next_cached else 0.0
        self.last_transition = mix.trans_type
        self._add_timeline_entry(curr_idx + 1, next_track, next_dur_s, mix.trans_type, len(mix.overlap) / 1000.0)
        self._write_segment(mix.overlap)
        # The overlap already played the head of the next track
        return mix.consumed_ms / 1000.0

    def _write_pcm_to_mpv(self, raw_data: Optional[bytes]) -> bool:
        """Write raw PCM byte buffer directly into MPV's stdin pipe."""
        if not raw_data or not self.mpv_process or not self.mpv_process.stdin:
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

        "mixing" is True exactly while a transition overlap is audible.
        """
        if not self.ipc:
            return {"now_playing": None, "time_pos": 0.0, "duration": 0.0, "paused": False,
                    "mixing": False, "mode": self.mode_label}

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
        mixing = False

        with self._lock:
            entry = self._audible_entry(mpv_time)
            if entry is not None:
                curr_track = entry["track"]
                track_pos = max(0.0, mpv_time - entry["stream_start_s"])
                track_dur = entry["duration"]
                active_trans = entry["transition"]
                mixing = bool(active_trans) and mpv_time < entry.get("mix_end_s", 0.0)
                self.playing_idx = entry["idx"]

            if not curr_track and self.tracks:
                curr_track = self.tracks[self.playing_idx] if self.playing_idx < len(self.tracks) else None

        return {
            "now_playing": curr_track.display_title() if curr_track else None,
            "track": curr_track,
            "time_pos": track_pos,
            "duration": track_dur,
            "paused": is_paused,
            "transition": active_trans,
            "mixing": mixing,
            "mode": self.mode_label,
            "playing_idx": self.playing_idx,
            "index": self.playing_idx,
        }

    def stop(self) -> None:
        """Cleanly tear down MPV subprocess, IPC client, and streaming threads."""
        self._quit_flag = True
        self._invalidate_mix()

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
