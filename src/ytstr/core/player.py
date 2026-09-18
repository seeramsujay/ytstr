"""
Unified player coordinator connecting engines, cache, and user interfaces.
"""
import signal
import sys
from typing import List, Optional

from ytstr.config import DEFAULT_CROSSFADE_SEC, VERSION
from ytstr.core.playlist import shuffle_tracks
from ytstr.core.types import PlaybackMode, Track
from ytstr.downloader.cache import CacheManager
from ytstr.downloader.ytdlp import Downloader
from ytstr.playback.direct import DirectPlayer
from ytstr.playback.dj_player import DJPlayer
from ytstr.ui.input import KeyboardListener
from ytstr.ui.terminal import error, info, print_banner, print_track_card, success, warn


class YtstrCoordinator:
    """Coordinates playlist ingestion, cache management, playback engines, and keyboard input."""

    def __init__(
        self,
        target: str,
        mode: PlaybackMode = PlaybackMode.AUTO_DJ,
        shuffle: bool = True,
        save_dir: Optional[str] = None,
        crossfade_sec: float = DEFAULT_CROSSFADE_SEC,
    ):
        self.target = target
        self.mode = mode
        self.shuffle = shuffle
        self.save_dir = save_dir
        self.crossfade_sec = crossfade_sec

        self.tracks: List[Track] = []
        self.downloader = Downloader()
        self.cache_mgr = CacheManager(save_dir=save_dir)

        self.direct_player: Optional[DirectPlayer] = None
        self.dj_player: Optional[DJPlayer] = None
        self.keyboard_listener: Optional[KeyboardListener] = None

        self._install_signals()

    def _install_signals(self):
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum=None, frame=None):
        self.stop()
        sys.exit(0)

    def run(self):
        """Fetch tracks, initialize engine, print banner, and enter playback loop."""
        info("Fetching audio tracks...")
        self.tracks = self.downloader.fetch_playlist_tracks(self.target)

        if not self.tracks:
            error("Could not find any tracks for target query or playlist.")
            self.cache_mgr.cleanup()
            return

        success(f"Found {len(self.tracks)} tracks")

        if self.shuffle:
            warn("Shuffling playlist...")
            self.tracks = shuffle_tracks(self.tracks)

        print_banner(VERSION, self.mode, save_dir=self.save_dir or "")

        # Launch appropriate engine
        if self.mode in (PlaybackMode.NO_MIX, PlaybackMode.STREAM):
            self._start_direct_playback()
        else:
            self._start_dj_playback()

        self._start_keyboard_listener()

    def _on_track_change(self, idx: int, track: Track, transition: str = ""):
        next_track = self.tracks[idx + 1] if idx + 1 < len(self.tracks) else None
        print_track_card(idx, len(self.tracks), track, next_track, transition)

    def _start_direct_playback(self):
        is_stream = self.mode == PlaybackMode.STREAM
        self.direct_player = DirectPlayer(
            tracks=self.tracks,
            cache_manager=self.cache_mgr,
            downloader=self.downloader,
            direct_stream=is_stream,
            on_track_change=lambda idx, t: self._on_track_change(idx, t, ""),
        )
        self.direct_player.start()

    def _start_dj_playback(self):
        is_light = self.mode == PlaybackMode.LIGHT_MIX
        self.dj_player = DJPlayer(
            tracks=self.tracks,
            cache_manager=self.cache_mgr,
            downloader=self.downloader,
            light_mix=is_light,
            crossfade_sec=self.crossfade_sec,
            on_track_change=self._on_track_change,
        )
        self.dj_player.start()

    def _start_keyboard_listener(self):
        def on_pause():
            if self.direct_player:
                self.direct_player.toggle_pause = True
            elif self.dj_player:
                self.dj_player.toggle_pause = True

        def on_next():
            if self.direct_player:
                self.direct_player.skip_to_next = True
            elif self.dj_player:
                self.dj_player.skip_to_next = True

        def on_prev():
            if self.direct_player:
                self.direct_player.skip_to_prev = True
            elif self.dj_player:
                self.dj_player.skip_to_prev = True

        def on_vol_up():
            ipc = (
                self.direct_player.ipc if self.direct_player else (self.dj_player.ipc if self.dj_player else None)
            )
            if ipc:
                ipc.adjust_volume(5)

        def on_vol_down():
            ipc = (
                self.direct_player.ipc if self.direct_player else (self.dj_player.ipc if self.dj_player else None)
            )
            if ipc:
                ipc.adjust_volume(-5)

        def on_quit():
            self.stop()

        self.keyboard_listener = KeyboardListener(
            on_toggle_pause=on_pause,
            on_next=on_next,
            on_prev=on_prev,
            on_volume_up=on_vol_up,
            on_volume_down=on_vol_down,
            on_quit=on_quit,
        )

        try:
            self.keyboard_listener.start()
        except Exception:
            pass
        finally:
            self.stop()
            success("\nPlayback stopped.")

    def stop(self):
        """Halt all playback and cleanup temporary directory."""
        if self.direct_player:
            self.direct_player.stop()
        if self.dj_player:
            self.dj_player.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        self.cache_mgr.cleanup()
