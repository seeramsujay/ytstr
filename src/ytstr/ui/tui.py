"""
Terminal User Interface (TUI) for YouTube Music and ytstr.
Built using standard library curses for zero-dependency, ultra-lightweight performance.
Integrates direct MPV playback, automatic continuous radio queuing, and library browsing.
"""
from __future__ import annotations

import curses
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ytstr.config import DEFAULT_CROSSFADE_SEC, PLAYLIST_FILE, VERSION
from ytstr.core.types import Track
from ytstr.downloader.cache import CacheManager
from ytstr.downloader.ytdlp import Downloader
from ytstr.playback.dj_player import DJPlayer
from ytstr.playback.mpv_ipc import MPVIPCClient, spawn_mpv_process
from ytstr.ytm.auth import AuthManager
from ytstr.ytm.client import YouTubeMusicClient

try:
    from pynput import keyboard as pynput_keyboard
except ImportError:
    pynput_keyboard = None

SOCKET_PATH = f"/tmp/ytstr_tui_mpv_{os.getpid()}.sock"

TAB_RECOMMENDED = 0
TAB_PLAYLISTS = 1
TAB_LIKED = 2
TAB_QUEUE = 3
TAB_SEARCH = 4
TAB_LOGIN = 5
TAB_NAMES = ["🎵 Recommended", "📁 My Playlists", "❤️ Liked Songs", "📻 Radio Queue", "🔍 Search", "🔑 Account"]

MODES = ["--no-mix", "--light-mix", "--stream", ""]
MODE_LABELS = ["Direct Low-RAM", "Light Mix", "Direct Stream", "Auto-DJ (Spectral)"]


class TUIApp:
    """Terminal User Interface for personalized YouTube Music streaming with radio queues."""

    def __init__(self, stdscr, initial_mode_idx: int = 0) -> None:
        self.stdscr = stdscr
        self.auth_mgr = AuthManager()
        self.client = YouTubeMusicClient(self.auth_mgr)
        self.cache_mgr = CacheManager(session_id=f"tui_{os.getpid()}")
        self.downloader = Downloader()

        self.current_tab = TAB_RECOMMENDED
        self.mode_idx = initial_mode_idx  # Default to Direct Low-RAM (0)

        # Navigation & list items
        self.items: List[Any] = []
        self.selected_idx = 0
        self.scroll_offset = 0

        # Playlist drill-down state
        self.in_playlist_name: Optional[str] = None
        self.playlist_back_items: List[Any] = []
        self.playlist_back_selected = 0

        # Cached tab items
        self.recommended_sections: List[Dict[str, Any]] = []
        self.my_playlists: List[Dict[str, Any]] = []
        self.liked_tracks: List[Track] = []
        self.queue_tracks: List[Track] = []
        self.current_queue_idx: int = -1
        self.search_results: List[Track] = []
        self.saved_local_playlists: List[Tuple[str, str]] = []

        # Playback status via embedded MPV or DJPlayer
        self._active_engine: str = "none"  # "none", "direct", "dj"
        self.mpv_process: Optional[subprocess.Popen] = None
        self.ipc = MPVIPCClient(SOCKET_PATH)
        self.dj_player: Optional[DJPlayer] = None
        self.pending_dj_handoff = False

        self.now_playing: Optional[str] = None
        self.next_playing: Optional[str] = None
        self.is_paused = False
        self.time_pos = 0.0
        self.duration = 0.0
        self.status_msg = "Ready. Select a track to play and start continuous radio. Press ? for help."

        # Loading & thread state
        self.is_loading = False
        self.loading_text = ""
        self.search_query = ""
        self._quit_flag = False
        self._fetching_radio = False

        # Suppress uncaught thread tracebacks from corrupting the curses screen
        def _thread_excepthook(args):
            try:
                err_path = "/tmp/ytstr_thread_error.log"
                with open(err_path, "a") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Thread {args.thread.name}: {args.exc_type.__name__}: {args.exc_value}\n")
            except Exception:
                pass
        threading.excepthook = _thread_excepthook

        self.global_listener = None
        self._start_global_media_listener()
        self._setup_curses()
        self._ensure_mpv(raw_pcm_mode=False)
        self.fetch_recommended_async()

        # Start continuous sliding-window cache worker (next 2 songs + previous song < 30 MB)
        self._cache_thread = threading.Thread(target=self._cache_worker, daemon=True, name="ytstr-tui-cache")
        self._cache_thread.start()

    def _setup_curses(self) -> None:
        """Initialize curses screen, colors, and input polling options."""
        try:
            curses.curs_set(0)
        except Exception:
            pass
        curses.use_default_colors()
        self.stdscr.timeout(200)

    @property
    def active_engine(self) -> str:
        """Return currently active engine family ('dj', 'direct', or 'none')."""
        if self._active_engine != "none":
            return self._active_engine
        if self.dj_player:
            return "dj"
        if self.now_playing:
            return "direct"
        return "none"

    @active_engine.setter
    def active_engine(self, val: str) -> None:
        self._active_engine = val

    @property
    def active_ipc(self) -> Optional[MPVIPCClient]:
        """Return the active MPVIPCClient instance from either DJPlayer or Direct MPV."""
        if self.active_engine == "dj" and self.dj_player and self.dj_player.ipc:
            return self.dj_player.ipc
        return self.ipc

        if curses.has_colors():
            try:
                curses.init_pair(1, curses.COLOR_RED, -1)     # Accent / logo / headers
                curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)  # Selected row
                curses.init_pair(3, curses.COLOR_GREEN, -1)   # Green / playing
                curses.init_pair(4, curses.COLOR_CYAN, -1)    # Playlists
                curses.init_pair(5, curses.COLOR_YELLOW, -1)  # Warnings / prompts
                curses.init_pair(6, curses.COLOR_WHITE, -1)   # Normal text
            except Exception:
                pass

    def _ensure_mpv(self, raw_pcm_mode: bool = False) -> None:
        """Ensure background MPV process is active and listening on IPC socket."""
        if self.mpv_process and self.mpv_process.poll() is None:
            return
        try:
            self.mpv_process = spawn_mpv_process(SOCKET_PATH, raw_pcm_mode=raw_pcm_mode)
            time.sleep(0.15)
        except Exception:
            pass

    def _start_global_media_listener(self) -> None:
        """Intercept hardware keyboard media keys (Play/Pause, Next, Prev, Volume)."""
        if not pynput_keyboard:
            return

        def on_press(key):
            try:
                if key in (pynput_keyboard.Key.media_play_pause, pynput_keyboard.Key.f8):
                    self.toggle_pause()
                elif key in (pynput_keyboard.Key.media_next, pynput_keyboard.Key.f9):
                    self._skip_next()
                elif key in (pynput_keyboard.Key.media_previous, pynput_keyboard.Key.f7):
                    self._skip_prev()
                elif key == getattr(pynput_keyboard.Key, 'media_volume_up', None):
                    self._adjust_volume(5)
                elif key == getattr(pynput_keyboard.Key, 'media_volume_down', None):
                    self._adjust_volume(-5)
            except Exception:
                pass

        try:
            self.global_listener = pynput_keyboard.Listener(on_press=on_press)
            self.global_listener.daemon = True
            self.global_listener.start()
        except Exception:
            pass

    def cleanup(self) -> None:
        """Clean up MPV, workers, and temporary sockets on exit."""
        self._quit_flag = True
        if self.global_listener:
            try:
                self.global_listener.stop()
            except Exception:
                pass
        self.stop_playback()
        self.cache_mgr.cleanup()
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass

    def _handle_input(self, ch: int) -> None:
        """Top-level key dispatcher delegating to specialized handlers."""
        if self._handle_navigation_keys(ch):
            return
        if self._handle_playback_keys(ch):
            return
        self._handle_action_keys(ch)

    def _handle_navigation_keys(self, ch: int) -> bool:
        """Handle screen navigation, scrolling, and tab switching."""
        # Back navigation from playlist drill-down: Backspace, Esc, or 'h'
        if self.in_playlist_name and ch in (127, 8, 27, ord('h'), ord('H'), curses.KEY_BACKSPACE):
            self._exit_playlist_view()
            return True

        # Tab switching (1-6)
        if ord('1') <= ch <= ord('6'):
            self._switch_tab(ch - ord('1'))
            return True

        # Up / Down / PageUp / PageDown / j / k
        if ch in (curses.KEY_UP, ord('k'), ord('K')):
            self._move_selection(-1)
            return True
        if ch in (curses.KEY_DOWN, ord('j'), ord('J')):
            self._move_selection(1)
            return True
        if ch == curses.KEY_PPAGE:
            self._move_selection(-10)
            return True
        if ch == curses.KEY_NPAGE:
            self._move_selection(10)
            return True

        return False

    def _handle_playback_keys(self, ch: int) -> bool:
        """Handle seeking, volume, pause, track skipping, and mode toggling."""
        if ch in (10, 13, curses.KEY_ENTER):
            self._activate_selected()
            return True
        if ch == ord(' '):
            self.toggle_pause()
            return True
        if ch in (curses.KEY_RIGHT, ord('l'), ord('L')):
            self._seek(5)
            return True
        if ch in (curses.KEY_LEFT, ord('h'), ord('H')):
            self._seek(-5)
            return True
        if ch in (ord(']'), curses.KEY_SRIGHT):
            self._seek(30)
            return True
        if ch in (ord('['), curses.KEY_SLEFT):
            self._seek(-30)
            return True
        if ch in (ord('>'), ord('.'), ord('n'), ord('N')):
            self._skip_next()
            return True
        if ch in (ord('<'), ord(','), ord('p'), ord('P')):
            self._skip_prev()
            return True
        if ch in (ord('0'), ord('+'), ord('=')):
            self._adjust_volume(5)
            return True
        if ch in (ord('9'), ord('-'), ord('_')):
            self._adjust_volume(-5)
            return True
        if ch in (ord('m'), ord('M')):
            self._handle_mode_switch()
            return True
        if ch in (ord('x'), ord('X')):
            self.stop_playback()
            self.status_msg = "Playback stopped."
            return True

        return False

    def _handle_action_keys(self, ch: int) -> bool:
        """Handle search, save, queue drop, and playlist bulk play."""
        if ch in (ord('P'),):
            self._play_playlist_direct()
            return True
        if ch == ord('/'):
            self._prompt_search()
            return True
        if ch in (ord('s'), ord('S')):
            self._save_selected()
            return True
        if ch in (ord('d'), ord('D'), curses.KEY_DC):
            self._remove_selected_from_queue()
            return True
        if ch in (ord('r'), ord('R')):
            self._start_radio_selected()
            return True

        return False

    def _seek(self, seconds: float) -> None:
        """Seek forward or backward by the specified amount."""
        if self.active_ipc:
            self.active_ipc.seek(seconds, "relative")
            self.time_pos = max(0.0, min(self.duration, self.time_pos + seconds))
            direction = "→" if seconds > 0 else "←"
            self.status_msg = f"Seek {int(seconds):+d}s ({direction})"

    def _skip_next(self) -> None:
        """Skip to next track in queue or playlist."""
        next_idx = self.current_queue_idx + 1
        if 0 <= next_idx < len(self.queue_tracks):
            self.current_queue_idx = next_idx
            next_track = self.queue_tracks[next_idx]
            if self.mode_idx in (1, 3):
                if self.active_engine == "dj" and self.dj_player:
                    self.dj_player.jump_to(next_idx)
                else:
                    self.stop_playback(keep_queue=True)
                    self.current_queue_idx = next_idx
                    self.play_track_and_start_radio(next_track, existing_queue=self.queue_tracks, start_idx=next_idx)
            else:
                if self.active_engine == "dj":
                    self.stop_playback(keep_queue=True)
                self._play_direct_track_at_index(next_idx)
            self.now_playing = next_track.display_title()
            self.duration = next_track.duration_sec
            self.time_pos = 0.0
            self._update_next_track()
            self.status_msg = f"⏭️ Skipped to: {next_track.display_title()}"
            if self.current_tab == TAB_QUEUE:
                self.selected_idx = next_idx
        elif self.active_ipc:
            self.active_ipc.playlist_next()
            self.status_msg = "End of queue reached."

    def _skip_prev(self) -> None:
        """Rewind within track or jump to previous track in queue."""
        # If currently playing track has progressed more than 3.0 seconds, rewind track to beginning
        if self.time_pos > 3.0:
            if self.active_ipc:
                self.active_ipc.seek(0.0, "absolute")
                self.time_pos = 0.0
                self.status_msg = "⏮️ Rewound track to beginning."
                return

        # Otherwise step backwards in the queue
        prev_idx = self.current_queue_idx - 1
        if 0 <= prev_idx < len(self.queue_tracks):
            prev_track = self.queue_tracks[prev_idx]
            self.current_queue_idx = prev_idx
            if self.mode_idx in (1, 3):
                if self.active_engine == "dj" and self.dj_player:
                    self.dj_player.jump_to(prev_idx)
                else:
                    self.stop_playback(keep_queue=True)
                    self.current_queue_idx = prev_idx
                    self.play_track_and_start_radio(prev_track, existing_queue=self.queue_tracks, start_idx=prev_idx)
            else:
                if self.active_engine == "dj":
                    self.stop_playback(keep_queue=True)
                self._play_direct_track_at_index(prev_idx)
            self.now_playing = prev_track.display_title()
            self.duration = prev_track.duration_sec
            self.time_pos = 0.0
            self._update_next_track()
            self.status_msg = f"⏮️ Rewound to: {prev_track.display_title()}"
            if self.current_tab == TAB_QUEUE:
                self.selected_idx = prev_idx
        else:
            if self.active_ipc:
                self.active_ipc.seek(0.0, "absolute")
            self.status_msg = "Already at first track in queue."

    def _play_direct_track_at_index(self, idx: int) -> None:
        """Play track at specified queue index using cache if available or stream URL."""
        if not (0 <= idx < len(self.queue_tracks)):
            return
        track = self.queue_tracks[idx]
        self.current_queue_idx = idx
        self.now_playing = track.display_title()
        self.duration = track.duration_sec
        self.time_pos = 0.0
        self._update_next_track()

        # In Mode 2 (Direct Stream): zero-disk direct stream URL
        if self.mode_idx == 2:
            target = self.downloader.get_direct_stream_url(track.id) or track.web_url
        else:
            cached = self.cache_mgr.find_cached_file(track)
            if cached and cached.exists():
                target = str(cached)
            else:
                target = self.downloader.get_direct_stream_url(track.id) or track.web_url

        self.active_engine = "direct"
        self._ensure_mpv(raw_pcm_mode=False)
        if not self.ipc:
            self.ipc = MPVIPCClient(SOCKET_PATH)
        if self.ipc:
            self.ipc.load_file(target, mode="replace")

    def _adjust_volume(self, delta: float) -> None:
        """Adjust mpv audio volume."""
        if self.active_ipc:
            self.active_ipc.adjust_volume(delta)
            sign = "+" if delta > 0 else ""
            self.status_msg = f"Volume {sign}{int(delta)}%"

    def _handle_mode_switch(self) -> None:
        """Cycle playback mode and manage live handoff between Direct and DJ engines."""
        self.mode_idx = (self.mode_idx + 1) % len(MODES)
        mode_label = MODE_LABELS[self.mode_idx]
        is_dj_mode = self.mode_idx in (1, 3)

        if not self.now_playing or self.active_engine == "none":
            self.status_msg = f"Playback mode: {mode_label}"
            return

        if self.active_engine == "dj":
            if is_dj_mode:
                if self.dj_player:
                    self.dj_player.light_mix = (self.mode_idx == 1)
                self.status_msg = f"🎛️ Switched to {mode_label}"
            else:
                self.pending_dj_handoff = False
                self.status_msg = f"Switched to {mode_label}: Current song continuing, switching mode on next track..."
        elif self.active_engine == "direct":
            if not is_dj_mode:
                self.pending_dj_handoff = False
                self.status_msg = f"Switched to {mode_label} (active on next track)"
            else:
                self.pending_dj_handoff = True
                self.status_msg = f"🎛️ Switched to {mode_label}: Song continuing, DJ engine warming up for handoff..."

                def warm_up():
                    next_idx = self.current_queue_idx + 1
                    if 0 <= next_idx < len(self.queue_tracks):
                        target_path = self.cache_mgr.get_track_cache_path(self.queue_tracks[next_idx], "opus")
                        if not self.cache_mgr.track_is_cached(self.queue_tracks[next_idx]):
                            self.downloader.download_track(self.queue_tracks[next_idx], target_path)
                threading.Thread(target=warm_up, daemon=True).start()

    def _switch_tab(self, new_tab: int) -> None:
        """Change active UI tab and load its contents if empty."""
        self.current_tab = new_tab
        self.selected_idx = 0
        self.scroll_offset = 0
        self.in_playlist_name = None

        if new_tab == TAB_RECOMMENDED:
            if not self.recommended_sections:
                self.fetch_recommended_async()
            else:
                self._rebuild_items_from_sections(self.recommended_sections)
        elif new_tab == TAB_PLAYLISTS:
            if not self.my_playlists:
                self.fetch_playlists_async()
            else:
                self.items = list(self.my_playlists)
        elif new_tab == TAB_LIKED:
            if not self.liked_tracks:
                self.fetch_liked_async()
            else:
                self.items = list(self.liked_tracks)
        elif new_tab == TAB_QUEUE:
            self.items = list(self.queue_tracks)
            if 0 <= self.current_queue_idx < len(self.items):
                self.selected_idx = self.current_queue_idx
                self.scroll_offset = max(0, self.selected_idx - 5)
        elif new_tab == TAB_SEARCH:
            self.items = list(self.search_results)
            if not self.items and not self.search_query:
                self.status_msg = "Press '/' to search YouTube Music catalog."
        elif new_tab == TAB_LOGIN:
            self._build_login_items()

    def _move_selection(self, delta: int) -> None:
        """Move cursor selection up or down with wrapping bounds."""
        if not self.items:
            self.selected_idx = 0
            return
        self.selected_idx = max(0, min(len(self.items) - 1, self.selected_idx + delta))

    def _activate_selected(self) -> None:
        """Perform primary action on currently selected item."""
        if not self.items or self.selected_idx >= len(self.items):
            return

        item = self.items[self.selected_idx]

        if self.current_tab == TAB_LOGIN:
            self._handle_login_action(item)
            return

        if isinstance(item, dict) and item.get("type") == "section_header":
            if self.selected_idx + 1 < len(self.items):
                self.selected_idx += 1
                self._activate_selected()
            return

        if self.current_tab == TAB_QUEUE and isinstance(item, Track):
            target_idx = self.selected_idx
            if self.mode_idx in (1, 3):
                if self.active_engine == "dj" and self.dj_player:
                    self.dj_player.jump_to(target_idx)
                else:
                    self.stop_playback(keep_queue=True)
                    self.current_queue_idx = target_idx
                    self.play_track_and_start_radio(item, existing_queue=self.queue_tracks, start_idx=target_idx)
            else:
                if self.active_engine == "dj":
                    self.stop_playback(keep_queue=True)
                self._play_direct_track_at_index(target_idx)
            self.current_queue_idx = target_idx
            self.now_playing = item.display_title()
            self.duration = item.duration_sec
            self.time_pos = 0.0
            self._update_next_track()
            self.status_msg = f"▶ Jumped to: {item.display_title()}"
            return

        if isinstance(item, Track):
            self.play_track_and_start_radio(item)
        elif isinstance(item, dict) and item.get("type") == "playlist":
            self._open_playlist_drilldown(item.get("id", ""), item.get("title", "Playlist"))
        elif isinstance(item, tuple) and item[0] == "saved":
            _, name, url = item
            self._play_external_target(url, f"Saved: {name}")

    def _handle_login_action(self, item: Any) -> None:
        """Execute selected authentication action."""
        action_code = item.get("action") if isinstance(item, dict) else None
        if action_code == "auto_login":
            self.status_msg = "Extracting session cookies from installed browsers (Zen, Firefox, Chrome...)..."
            self._run_browser_login_async("auto")
        elif action_code == "zen_login":
            self.status_msg = "Extracting session cookies from Zen Browser..."
            self._run_browser_login_async("zen")
        elif action_code == "open_browser":
            self.auth_mgr.open_browser_for_login()
            self.status_msg = "Opened https://music.youtube.com in default browser."
        elif action_code == "logout":
            self.auth_mgr.logout()
            self.client._init_ytm()
            self.status_msg = "Logged out. Credentials cleared."
            self._build_login_items()

    def play_track_and_start_radio(
        self,
        track: Track,
        existing_queue: Optional[List[Track]] = None,
        start_idx: int = 0,
    ) -> None:
        """Play track immediately in MPV or DJPlayer and automatically queue its radio recommendations."""
        self.stop_playback(keep_queue=False)
        self.now_playing = track.display_title()
        self.next_playing = "Loading radio queue..." if not existing_queue else (
            existing_queue[start_idx + 1].display_title() if len(existing_queue) > start_idx + 1 else None
        )
        self.is_paused = False
        self.time_pos = 0.0
        self.duration = track.duration_sec
        self.status_msg = f"▶ Playing: {track.display_title()} | Queuing radio..."

        is_dj_mode = self.mode_idx in (1, 3)

        if existing_queue:
            self.queue_tracks = list(existing_queue)
            self.current_queue_idx = start_idx
        else:
            self.queue_tracks = [track]
            self.current_queue_idx = 0

        if is_dj_mode:
            is_light = (self.mode_idx == 1)
            self.active_engine = "dj"
            self.dj_player = DJPlayer(
                tracks=self.queue_tracks,
                cache_manager=self.cache_mgr,
                downloader=self.downloader,
                light_mix=is_light,
                crossfade_sec=DEFAULT_CROSSFADE_SEC,
                on_track_change=self._on_dj_track_change,
                custom_socket=SOCKET_PATH,
                start_idx=self.current_queue_idx,
            )
            self.dj_player.start()
        else:
            self.active_engine = "direct"
            self._play_direct_track_at_index(self.current_queue_idx)

        # Asynchronously fetch radio if existing_queue wasn't provided
        if not existing_queue:
            track_id = track.id

            def worker():
                try:
                    radio_tracks = self.client.get_watch_playlist_tracks(track_id, limit=35)
                    if radio_tracks:
                        filtered = [t for t in radio_tracks if t.id != track_id]
                        self.queue_tracks.extend(filtered)
                        if self.dj_player:
                            self.dj_player.append_tracks(filtered)
                        self._update_next_track()
                        self.status_msg = f"▶ Playing: {track.display_title()} | 📻 Radio: {len(filtered)} tracks queued"

                        if self.current_tab == TAB_QUEUE:
                            self.items = list(self.queue_tracks)
                    else:
                        self.next_playing = None
                        self.status_msg = f"▶ Playing: {track.display_title()}"
                except Exception as e:
                    self.status_msg = f"▶ Playing: {track.display_title()} (Radio error: {e})"

            threading.Thread(target=worker, daemon=True, name="ytstr-initial-radio").start()

    def _cache_worker(self) -> None:
        """
        Background cache worker for active playback:
        Prefetches next two songs and previous song (< 30 MB),
        and dynamically expands the radio queue when approaching queue end.
        """
        while not self._quit_flag:
            curr_idx = self.current_queue_idx
            tracks = list(self.queue_tracks)
            total = len(tracks)

            if total == 0 or curr_idx < 0 or curr_idx >= total or self.mode_idx == 2 or self.active_engine == "dj":
                time.sleep(0.4)
                continue

            # Check if radio queue needs expansion (nearing end)
            if total - curr_idx <= 5 and not self._fetching_radio:
                self._expand_radio_queue()

            # Targets:
            # 1. Current track
            # 2. Next track 1 (curr_idx + 1)
            # 3. Next track 2 (curr_idx + 2)
            # 4. Previous track (curr_idx - 1)
            targets = [curr_idx, curr_idx + 1, curr_idx + 2]
            if curr_idx > 0:
                targets.append(curr_idx - 1)

            downloaded_something = False
            for idx in targets:
                if self._quit_flag or self.current_queue_idx != curr_idx:
                    break
                if 0 <= idx < total:
                    track = tracks[idx]
                    if not self.cache_mgr.track_is_cached(track):
                        target_path = self.cache_mgr.get_track_cache_path(track, "opus")
                        self.downloader.download_track(track, target_path)
                        downloaded_something = True
                        break

            # Enforce sliding window pruning with 30MB limit
            self.cache_mgr.prune_window(curr_idx, tracks)

            if not downloaded_something:
                time.sleep(0.35)

    def _expand_radio_queue(self) -> None:
        """Fetch additional radio recommendations when approaching queue end."""
        if self._fetching_radio or not self.queue_tracks:
            return
        self._fetching_radio = True
        seed_track = self.queue_tracks[-1]

        def worker():
            try:
                radio_tracks = self.client.get_watch_playlist_tracks(seed_track.id, limit=25)
                if radio_tracks:
                    existing_ids = {t.id for t in self.queue_tracks}
                    filtered = [t for t in radio_tracks if t.id not in existing_ids]
                    if filtered:
                        self.queue_tracks.extend(filtered)
                        if self.dj_player:
                            self.dj_player.append_tracks(filtered)
                        if self.current_tab == TAB_QUEUE:
                            self.items = list(self.queue_tracks)
                        self._update_next_track()
            finally:
                self._fetching_radio = False

        threading.Thread(target=worker, daemon=True, name="ytstr-radio-expand").start()

    def _on_dj_track_change(self, idx: int, track: Track, transition: str = "") -> None:
        """Callback from DJ engine when a new track boundary is reached."""
        self.current_queue_idx = idx
        self.now_playing = track.display_title()
        self.duration = track.duration_sec
        self.time_pos = 0.0
        self._update_next_track()
        if transition:
            self.status_msg = f"▶ Playing: {self.now_playing} | 🎛️ Auto-DJ: {transition}"
        else:
            self.status_msg = f"▶ Playing: {self.now_playing}"
        if self.current_tab == TAB_QUEUE:
            self.items = list(self.queue_tracks)

    def _update_next_track(self) -> None:
        """Update next_playing label based on queue position."""
        next_idx = self.current_queue_idx + 1
        if 0 <= next_idx < len(self.queue_tracks):
            self.next_playing = self.queue_tracks[next_idx].display_title()
        else:
            self.next_playing = None

    def _open_playlist_drilldown(self, playlist_id: str, title: str) -> None:
        """Fetch tracks inside a playlist and view them interactively."""
        self.is_loading = True
        self.loading_text = f"Opening '{title}'..."
        self.playlist_back_items = list(self.items)
        self.playlist_back_selected = self.selected_idx
        self.in_playlist_name = title

        def worker():
            try:
                tracks = self.client.get_playlist_tracks(playlist_id)
                self.is_loading = False
                if tracks:
                    self.items = tracks
                    self.selected_idx = 0
                    self.scroll_offset = 0
                    self.status_msg = f"Viewing playlist: '{title}' ({len(tracks)} tracks)"
                else:
                    self.items = []
                    self.status_msg = f"No tracks found in '{title}'."
            except Exception as e:
                self.is_loading = False
                self.status_msg = f"Failed opening '{title}': {e}"

        threading.Thread(target=worker, daemon=True, name="ytstr-pl-drilldown").start()

    def _exit_playlist_view(self) -> None:
        """Return from playlist drill-down view back to top-level playlists."""
        if self.playlist_back_items:
            self.items = self.playlist_back_items
            self.selected_idx = self.playlist_back_selected
            self.scroll_offset = max(0, self.selected_idx - 5)
        self.in_playlist_name = None
        self.status_msg = "Back to playlists."

    def _play_playlist_direct(self) -> None:
        """Play entire playlist: load track 1 and queue the rest."""
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if isinstance(item, dict) and item.get("type") == "playlist":
            pl_id = item.get("id", "")
            title = item.get("title", "Playlist")
            self.status_msg = f"Queuing playlist '{title}'..."

            def worker():
                try:
                    tracks = self.client.get_playlist_tracks(pl_id)
                    if tracks:
                        first = tracks[0]
                        self.play_track_and_start_radio(first, existing_queue=tracks)
                        self.status_msg = f"▶ Playing '{title}' ({len(tracks)} tracks queued)"
                    else:
                        self.status_msg = f"Could not load playlist '{title}'."
                except Exception as e:
                    self.status_msg = f"Failed playing '{title}': {e}"

            threading.Thread(target=worker, daemon=True, name="ytstr-pl-play").start()

    def _play_external_target(self, target: str, title: str) -> None:
        """Fallback to direct MPV playback for custom target URLs."""
        self._ensure_mpv(raw_pcm_mode=False)
        if self.ipc:
            self.ipc.load_file(target, mode="replace")

    def _remove_selected_from_queue(self) -> None:
        """Remove/skip selected song from upcoming radio queue."""
        if not self.queue_tracks:
            self.status_msg = "Queue is empty."
            return

        target_idx = -1
        if self.current_tab == TAB_QUEUE:
            if 0 <= self.selected_idx < len(self.queue_tracks):
                target_idx = self.selected_idx
        else:
            target_idx = self.current_queue_idx + 1

        if target_idx < 0 or target_idx >= len(self.queue_tracks):
            self.status_msg = "No upcoming song to remove from queue."
            return

        removed_track = self.queue_tracks[target_idx]
        title = removed_track.display_title()

        if self.dj_player:
            self.dj_player.remove_track(target_idx)

        # If removing the currently playing track, tell mpv to skip to next
        if target_idx == self.current_queue_idx:
            if self.dj_player and self.mode_idx in (1, 3):
                self.dj_player.skip_to_next = True
            elif self.ipc:
                self.ipc.playlist_next()
            del self.queue_tracks[target_idx]
            self.status_msg = f"Removed currently playing '{title[:25]}' and advanced."
        else:
            if self.ipc and not self.dj_player:
                self.ipc.playlist_remove(target_idx)
            del self.queue_tracks[target_idx]
            if target_idx < self.current_queue_idx:
                self.current_queue_idx -= 1
            self.status_msg = f"Removed '{title[:25]}' from radio queue (d)."

        self._update_next_track()
        if self.current_tab == TAB_QUEUE:
            self.items = list(self.queue_tracks)
            self.selected_idx = min(self.selected_idx, max(0, len(self.items) - 1))

    def _start_radio_selected(self) -> None:
        """Start a fresh radio station based on selected track."""
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if isinstance(item, Track):
            self.play_track_and_start_radio(item)

    def _save_selected(self) -> None:
        """Download currently selected track to ~/Music."""
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if isinstance(item, Track):
            music_dir = os.path.expanduser("~/Music")
            os.makedirs(music_dir, exist_ok=True)
            target = os.path.join(music_dir, f"{item.display_title()}.opus")
            self.status_msg = f"Downloading '{item.display_title()[:25]}' to ~/Music..."

            def worker():
                ok = self.downloader.download_track(item, target)
                self.status_msg = f"✓ Saved to ~/Music/{item.display_title()[:20]}.opus" if ok else f"✗ Failed downloading '{item.display_title()[:20]}'"

            threading.Thread(target=worker, daemon=True).start()

    def _prompt_search(self) -> None:
        """Prompt user for query in footer and fetch catalog search results."""
        curses.echo()
        curses.curs_set(1)
        max_y, max_x = self.stdscr.getmaxyx()
        prompt = "Search YouTube Music: "
        self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1), curses.color_pair(6))
        self.stdscr.addstr(max_y - 1, 0, prompt, curses.color_pair(5) | curses.A_BOLD)
        self.stdscr.refresh()

        try:
            inp = self.stdscr.getstr(max_y - 1, len(prompt), 60).decode("utf-8").strip()
        except Exception:
            inp = ""
        finally:
            curses.noecho()
            curses.curs_set(0)

        if not inp:
            self.status_msg = "Search canceled."
            return

        self.search_query = inp
        self.current_tab = TAB_SEARCH
        self.is_loading = True
        self.loading_text = f"Searching catalog for '{inp}'..."
        self.status_msg = self.loading_text

        def worker():
            try:
                tracks = self.client.search(inp, filter_type="songs", limit=30)
                self.is_loading = False
                self.search_results = tracks
                if self.current_tab == TAB_SEARCH:
                    self.items = list(tracks)
                    self.selected_idx = 0
                    self.scroll_offset = 0
                self.status_msg = f"Search '{inp}': found {len(tracks)} tracks."
            except Exception as e:
                self.is_loading = False
                self.status_msg = f"Search error: {e}"

        threading.Thread(target=worker, daemon=True, name="ytstr-search").start()

    def fetch_recommended_async(self) -> None:
        """Background worker to fetch personalized Home sections."""
        self.is_loading = True
        self.loading_text = "Fetching personalized recommendations..."

        def worker():
            try:
                sections = self.client.get_home_sections(limit=6)
                self.is_loading = False
                self.recommended_sections = sections
                if self.current_tab == TAB_RECOMMENDED:
                    self._rebuild_items_from_sections(sections)
                    if self.items:
                        self.status_msg = "Loaded personalized recommendations."
                    else:
                        self.status_msg = "No recommendations found. Press '/' to search catalog."
            except Exception as e:
                self.is_loading = False
                self.status_msg = f"Recommendations error: {e}"

        threading.Thread(target=worker, daemon=True, name="ytstr-fetch-recommended").start()

    def _rebuild_items_from_sections(self, sections: List[Dict[str, Any]]) -> None:
        """Flatten categorized sections into scrollable list with visual category headers."""
        flattened: List[Any] = []
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            title = sec.get("title", "Recommended")
            items = sec.get("items")
            if items is None:
                items = sec.get("contents") or []
            if not items:
                continue
            flattened.append({"type": "section_header", "title": title})
            flattened.extend(items)
        self.items = flattened
        if len(flattened) > 1 and isinstance(flattened[0], dict) and flattened[0].get("type") == "section_header":
            self.selected_idx = 1
        else:
            self.selected_idx = 0
        self.scroll_offset = 0

    def fetch_playlists_async(self) -> None:
        """Background worker to fetch user playlists + local saved playlists."""
        self.is_loading = True
        self.loading_text = "Fetching your playlists..."

        def worker():
            try:
                pls = self.client.get_user_playlists()
                self.is_loading = False
                self.my_playlists = pls
                if self.current_tab == TAB_PLAYLISTS and not self.in_playlist_name:
                    self.items = list(pls)
                    self.selected_idx = 0
                    self.scroll_offset = 0
                    self.status_msg = f"Loaded {len(pls)} user playlists."
            except Exception as e:
                self.is_loading = False
                self.status_msg = f"Failed to load playlists: {e}"

        threading.Thread(target=worker, daemon=True, name="ytstr-fetch-playlists").start()

    def fetch_liked_async(self) -> None:
        """Background worker to fetch Liked Songs library."""
        self.is_loading = True
        self.loading_text = "Fetching Liked Songs library..."

        def worker():
            try:
                liked = self.client.get_liked_songs(limit=100)
                self.is_loading = False
                self.liked_tracks = liked
                if self.current_tab == TAB_LIKED:
                    self.items = list(liked)
                    self.selected_idx = 0
                    self.scroll_offset = 0
                    self.status_msg = f"Loaded {len(liked)} Liked Songs."
            except Exception as e:
                self.is_loading = False
                self.status_msg = f"Failed to load liked songs: {e}"

        threading.Thread(target=worker, daemon=True, name="ytstr-fetch-liked").start()

    def _build_login_items(self) -> None:
        """Populate Account tab with interactive authentication actions."""
        logged_in = self.auth_mgr.is_authenticated()
        status_desc = "Session Authenticated (Full Access)" if logged_in else "Anonymous Mode (Public Catalog Only)"
        items = [
            {"action": "status", "title": "Current Status", "desc": status_desc},
            {"action": "auto_login", "title": "Auto-Detect Session Cookies", "desc": "Scan Zen, Firefox, Chrome, Chromium & Brave"},
            {"action": "zen_login", "title": "Zen Browser Session Import", "desc": "Import cookies directly from active Zen Browser profile"},
            {"action": "open_browser", "title": "Open YouTube Music in Browser", "desc": "Launch browser to sign in to your Google Account"},
        ]
        if logged_in:
            items.append({"action": "logout", "title": "Log Out", "desc": "Clear stored session credentials and reset client"})
        self.items = items
        self.selected_idx = 1 if not logged_in else 0
        self.scroll_offset = 0

    def _run_browser_login_async(self, browser_mode: str) -> None:
        """Background worker to extract cookies from specified browser."""
        self.is_loading = True
        self.loading_text = "Scanning browsers for YouTube Music authentication cookies..."

        def worker():
            if browser_mode == "zen":
                ok = self.auth_mgr.login_from_zen()
            else:
                ok = self.auth_mgr.login_from_browser()

            self.is_loading = False
            if ok:
                self.client._init_ytm()
                self.status_msg = "✓ Authentication successful! Personalized access enabled."
                self.fetch_recommended_async()
            else:
                self.status_msg = "✗ Could not extract session cookies. Ensure you are signed in at music.youtube.com."
            if self.current_tab == TAB_LOGIN:
                self._build_login_items()

        threading.Thread(target=worker, daemon=True).start()

    def toggle_pause(self) -> None:
        """Toggle playback pause state across either Direct MPV or Auto-DJ player."""
        if self.active_engine == "dj" and self.dj_player:
            self.dj_player.toggle_pause = True
        elif self.active_ipc:
            self.active_ipc.cycle_pause()
        self.is_paused = not self.is_paused
        state_str = "Paused" if self.is_paused else "Resumed"
        self.status_msg = f"Playback {state_str}."

    def stop_playback(self, keep_queue: bool = False) -> None:
        """Cleanly tear down MPV player or DJPlayer without corrupting the terminal."""
        if self.dj_player:
            try:
                self.dj_player.stop()
            except Exception:
                pass
            self.dj_player = None

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
                self.mpv_process.wait(timeout=0.5)
            except Exception:
                try:
                    self.mpv_process.kill()
                except Exception:
                    pass
            self.mpv_process = None

        self.active_engine = "none"

        if not keep_queue:
            self.now_playing = None
            self.next_playing = None
            self.queue_tracks = []
            self.current_queue_idx = -1
            self.is_paused = False
            self.time_pos = 0.0
            self.duration = 0.0

    def _update_playback_status(self) -> None:
        """Update playback time, duration, and track synchronization from MPV or DJPlayer."""
        if not os.path.exists(SOCKET_PATH):
            return

        # 1. DJ Player active
        if self.active_engine == "dj" and self.dj_player:
            st = self.dj_player.get_playback_status()
            self.time_pos = st.get("time_pos", 0.0)
            self.duration = st.get("duration", 0.0)
            self.is_paused = st.get("paused", False)
            if st.get("track"):
                self.now_playing = st["track"].display_title()
                new_idx = st.get("playing_idx", self.current_queue_idx)
                if new_idx != self.current_queue_idx:
                    self.current_queue_idx = new_idx
                    self._update_next_track()
                    # Check if user switched mode to Direct while DJ was playing
                    if self.mode_idx in (0, 2):
                        self.stop_playback(keep_queue=True)
                        self._play_direct_track_at_index(new_idx)
                        return
                if st.get("transition"):
                    self.status_msg = f"▶ Playing: {self.now_playing} | 🎛️ Auto-DJ: {st['transition']}"
                if self.current_tab == TAB_QUEUE:
                    self.items = list(self.queue_tracks)
            return

        # 2. Direct MPV active
        if self.active_engine == "direct":
            if not self.ipc:
                self._ensure_mpv(raw_pcm_mode=False)
                self.ipc = MPVIPCClient(SOCKET_PATH)

            try:
                pt = self.ipc.get_float_property("playback-time")
                if pt is None:
                    pt = self.ipc.get_float_property("time-pos")
                if pt is not None:
                    self.time_pos = max(0.0, pt)

                dur = self.ipc.get_float_property("duration")
                if dur is not None and dur > 0:
                    self.duration = dur

                p = self.ipc.get_bool_property("pause")
                if p is not None:
                    self.is_paused = p

                # Check if track ended
                eof = self.ipc.get_bool_property("eof-reached", default=False)
                idle = self.ipc.get_bool_property("idle-active", default=False)
                if self.time_pos > 0.5 and (eof or idle):
                    next_idx = self.current_queue_idx + 1
                    if next_idx < len(self.queue_tracks):
                        self.cache_mgr.on_track_finished(self.current_queue_idx, self.queue_tracks[self.current_queue_idx])
                        if self.mode_idx in (1, 3) or self.pending_dj_handoff:
                            self.pending_dj_handoff = False
                            next_track = self.queue_tracks[next_idx]
                            self.stop_playback(keep_queue=True)
                            self.current_queue_idx = next_idx
                            self.play_track_and_start_radio(next_track, existing_queue=self.queue_tracks, start_idx=next_idx)
                        else:
                            self._play_direct_track_at_index(next_idx)
                            self.status_msg = f"▶ Playing: {self.now_playing}"
                    else:
                        self.status_msg = "Queue ended."
            except Exception:
                pass

        # Check for pending DJ handoff as current track nears its end
        try:
            if self.pending_dj_handoff and self.duration > 0:
                remaining = self.duration - self.time_pos
                next_idx = self.current_queue_idx + 1
                if remaining <= 4.0 and next_idx < len(self.queue_tracks):
                    self.pending_dj_handoff = False
                    next_track = self.queue_tracks[next_idx]
                    self.status_msg = f"🎛️ Auto-DJ handoff: Transitioning to {next_track.display_title()}..."
                    self.stop_playback(keep_queue=True)
                    self.current_queue_idx = next_idx
                    self.play_track_and_start_radio(next_track, existing_queue=self.queue_tracks, start_idx=next_idx)
        except Exception:
            pass

    def _draw(self) -> None:
        """Render the complete TUI screen."""
        self.stdscr.erase()
        max_y, max_x = self.stdscr.getmaxyx()
        if max_y < 12 or max_x < 40:
            self.stdscr.addstr(0, 0, "Terminal too small!")
            self.stdscr.refresh()
            return

        self._draw_header(max_x)
        self._draw_tabs(max_x)
        self._draw_content(max_y, max_x)
        self._draw_playback_bar(max_y, max_x)
        self._draw_footer(max_y, max_x)
        self.stdscr.refresh()

    def _draw_header(self, max_x: int) -> None:
        """Render top branding and authentication badge."""
        auth_status = "Logged In ✓" if self.auth_mgr.is_authenticated() else "Not Logged In"
        auth_pair = curses.color_pair(3) if self.auth_mgr.is_authenticated() else curses.color_pair(5)

        header_left = f" ytstr v{VERSION} "
        header_right = f"[{auth_status}]  [{MODE_LABELS[self.mode_idx]}] "

        self.stdscr.attron(curses.A_BOLD)
        self.stdscr.addstr(0, 0, header_left, curses.color_pair(1))
        self.stdscr.addstr(0, len(header_left), "— YouTube Music Streamer", curses.color_pair(6))

        if len(header_right) < max_x - 30:
            self.stdscr.addstr(0, max_x - len(header_right), header_right, auth_pair)
        self.stdscr.attroff(curses.A_BOLD)

    def _draw_tabs(self, max_x: int) -> None:
        """Render interactive navigation tabs or breadcrumbs."""
        if self.in_playlist_name:
            tab_str = f" 📁 My Playlists > 🎵 {self.in_playlist_name} (Press Backspace or Esc to return) "
            self.stdscr.addstr(1, 0, tab_str[:max_x - 1], curses.A_REVERSE | curses.color_pair(4))
        else:
            tab_str = " "
            for i, name in enumerate(TAB_NAMES):
                if i == self.current_tab:
                    tab_str += f"[{name}]  "
                else:
                    tab_str += f" {name}   "
            self.stdscr.addstr(1, 0, tab_str[:max_x - 1], curses.A_REVERSE | curses.color_pair(4))

        self.stdscr.addstr(2, 0, "─" * (max_x - 1), curses.color_pair(6))

    def _draw_content(self, max_y: int, max_x: int) -> None:
        """Render scrollable items in the content area."""
        content_top = 3
        content_bottom = max_y - 4
        content_height = content_bottom - content_top

        if self.is_loading:
            loading_msg = f"⏳ {self.loading_text}"
            self.stdscr.addstr(content_top + 2, max(0, (max_x - len(loading_msg)) // 2), loading_msg, curses.color_pair(5) | curses.A_BOLD)
            return

        if not self.items:
            empty_msg = "No items available. Press '1' to refresh or '6' to login."
            if self.current_tab == TAB_SEARCH and not self.search_query:
                empty_msg = "Press '/' to search YouTube Music tracks and albums."
            self.stdscr.addstr(content_top + 2, max(0, (max_x - len(empty_msg)) // 2), empty_msg, curses.color_pair(6))
            return

        if self.selected_idx < self.scroll_offset:
            self.scroll_offset = self.selected_idx
        elif self.selected_idx >= self.scroll_offset + content_height:
            self.scroll_offset = self.selected_idx - content_height + 1

        for row_idx in range(content_height):
            item_idx = self.scroll_offset + row_idx
            if item_idx >= len(self.items):
                break

            y = content_top + row_idx
            item = self.items[item_idx]
            is_sel = (item_idx == self.selected_idx)

            line_str = ""
            attr = curses.A_NORMAL

            if isinstance(item, dict) and item.get("type") == "section_header":
                line_str = f"── {item.get('title', 'Section')} ──"
                attr = curses.A_BOLD | curses.color_pair(4)
            elif isinstance(item, Track):
                is_current = bool(self.now_playing and item.title and item.title in self.now_playing)
                prefix = " ▶ " if is_current else "   "
                line_str = f"{prefix}{item.display_title()}"
                attr = curses.color_pair(2) if is_sel else (curses.color_pair(3) if is_current else curses.color_pair(6))
            elif isinstance(item, dict) and item.get("type") == "playlist":
                line_str = f" 📁 {item.get('title', 'Playlist')} ({item.get('count', '?')} tracks)"
                attr = curses.color_pair(2) if is_sel else curses.color_pair(4)
            elif isinstance(item, dict) and "action" in item:
                line_str = f" {item.get('title', '')} — {item.get('desc', '')}"
                attr = curses.color_pair(2) if is_sel else curses.color_pair(6)
            elif isinstance(item, tuple) and len(item) == 2:
                name, url = item
                line_str = f" ★ {name} ({url})"
                attr = curses.color_pair(2) if is_sel else curses.color_pair(6)

            line_str = line_str.ljust(max_x - 1)[:max_x - 1]
            if is_sel:
                self.stdscr.addstr(y, 0, line_str, curses.A_REVERSE | curses.A_BOLD)
            else:
                self.stdscr.addstr(y, 0, line_str, attr)

    def _draw_playback_bar(self, max_y: int, max_x: int) -> None:
        """Render active playback bar, progress slider, and upcoming track label."""
        play_bar_y = max_y - 4
        self.stdscr.addstr(play_bar_y, 0, "─" * (max_x - 1), curses.color_pair(6))

        info_y = max_y - 3
        if self.now_playing:
            state_icon = "⏸ Paused" if self.is_paused else "▶ Playing"
            progress_bar = self._render_progress_bar(width=20)
            elapsed_fmt = self._fmt_sec(self.time_pos)
            dur_fmt = self._fmt_sec(self.duration) if self.duration > 0 else "--:--"

            play_info = f" {state_icon}: {self.now_playing}  [{progress_bar}] {elapsed_fmt}/{dur_fmt}"
            if len(play_info) > max_x - 2:
                play_info = play_info[:max_x - 5] + "..."
            self.stdscr.addstr(info_y, 0, play_info, curses.A_BOLD | curses.color_pair(3))

            next_y = max_y - 2
            next_info = f" ⏭  Next: {self.next_playing}" if self.next_playing else " ⏭  Next: [End of Queue]"
            self.stdscr.addstr(next_y, 0, next_info[:max_x - 1], curses.color_pair(6))
        else:
            self.stdscr.addstr(info_y, 0, f" Status: {self.status_msg}"[:max_x - 1], curses.color_pair(5))
            self.stdscr.addstr(max_y - 2, 0, " " * (max_x - 1))

    def _draw_footer(self, max_y: int, max_x: int) -> None:
        """Render keybindings footer bar."""
        footer_y = max_y - 1
        footer_str = " [Enter] Play/Drill  [Space] Pause  [←/→] Seek  [>/<] Skip  [d] Drop  [r] Radio  [m] Mode  [/] Search  [q] Quit "
        self.stdscr.addstr(footer_y, 0, footer_str[:max_x - 1], curses.A_REVERSE | curses.color_pair(4))

    def _render_progress_bar(self, width: int = 20) -> str:
        """Render ASCII playback progress bar."""
        if self.duration <= 0 or width <= 0:
            return " " * max(1, width)
        ratio = min(1.0, max(0.0, self.time_pos / self.duration))
        filled = int(ratio * width)
        if filled > 0:
            return "=" * (filled - 1) + ">" + "-" * (width - filled)
        return "-" * width

    def _fmt_sec(self, sec: float) -> str:
        """Format seconds into MM:SS format."""
        s = int(max(0.0, sec))
        m = s // 60
        s = s % 60
        return f"{m:02d}:{s:02d}"

    def run(self) -> None:
        """Main event loop."""
        while True:
            self._update_playback_status()
            self._draw()

            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue

            if ch in (ord('q'), ord('Q')):
                break
            if ch != -1:
                self._handle_input(ch)

        self.cleanup()


def main(initial_mode_idx: int = 0):
    try:
        curses.wrapper(lambda stdscr: TUIApp(stdscr, initial_mode_idx=initial_mode_idx).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
