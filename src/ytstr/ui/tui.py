"""
Terminal User Interface (TUI) for YouTube Music and ytstr.
Built using standard library curses for zero-dependency, ultra-lightweight performance.
Integrates direct MPV playback, automatic continuous radio queuing, and library browsing.
"""
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

try:
    from pynput import keyboard as pynput_keyboard
except ImportError:
    pynput_keyboard = None
from ytstr.ytm.auth import AuthManager
from ytstr.ytm.client import YouTubeMusicClient

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

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.auth_mgr = AuthManager()
        self.client = YouTubeMusicClient(self.auth_mgr)
        self.cache_mgr = CacheManager(session_id=f"tui_{os.getpid()}")
        self.downloader = Downloader()

        self.current_tab = TAB_RECOMMENDED
        self.mode_idx = 0  # Default to Direct Low-RAM

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

        self.global_listener = None
        self._start_global_media_listener()
        self._setup_curses()
        self._ensure_mpv(raw_pcm_mode=False)
        self.fetch_recommended_async()

    def _setup_curses(self):
        try:
            curses.curs_set(0)
        except Exception:
            pass
        curses.use_default_colors()
        self.stdscr.timeout(200)

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

    def _ensure_mpv(self, raw_pcm_mode: bool = False):
        """Ensure background MPV process is active and listening on IPC socket."""
        if self.mpv_process and self.mpv_process.poll() is None:
            return
        try:
            self.mpv_process = spawn_mpv_process(SOCKET_PATH, raw_pcm_mode=raw_pcm_mode)
            time.sleep(0.15)
        except Exception:
            pass

    def _start_global_media_listener(self):
        """Intercept hardware keyboard media keys (Play/Pause, Next, Prev, etc.)."""
        if not pynput_keyboard:
            return

        def on_press(key):
            try:
                # Play / Pause
                if key in (pynput_keyboard.Key.media_play_pause, pynput_keyboard.Key.f8):
                    self.toggle_pause()
                # Next Track
                elif key in (pynput_keyboard.Key.media_next, pynput_keyboard.Key.f9):
                    if self.dj_player and self.mode_idx in (1, 3):
                        self.dj_player.skip_to_next = True
                        self.status_msg = "Skipped to next track (Media Key)."
                    elif self.ipc:
                        self.ipc.send_command(["playlist-next"])
                        self.status_msg = "Skipped to next track (Media Key)."
                # Previous Track
                elif key in (pynput_keyboard.Key.media_previous, pynput_keyboard.Key.f7):
                    if self.dj_player and self.mode_idx in (1, 3):
                        self.dj_player.skip_to_prev = True
                        self.status_msg = "Skipped to previous track (Media Key)."
                    elif self.ipc:
                        self.ipc.send_command(["playlist-prev"])
                        self.status_msg = "Skipped to previous track (Media Key)."
                # Volume
                elif key == getattr(pynput_keyboard.Key, 'media_volume_up', None):
                    if self.ipc:
                        self.ipc.adjust_volume(5)
                        self.status_msg = "Volume +5%"
                elif key == getattr(pynput_keyboard.Key, 'media_volume_down', None):
                    if self.ipc:
                        self.ipc.adjust_volume(-5)
                        self.status_msg = "Volume -5%"
            except Exception:
                pass

        try:
            self.global_listener = pynput_keyboard.Listener(on_press=on_press)
            self.global_listener.daemon = True
            self.global_listener.start()
        except Exception:
            pass

    def cleanup(self):
        """Clean up MPV, workers, and temporary sockets on exit."""
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

    def _handle_input(self, ch: int):
        # Back navigation from playlist drill-down: Backspace, Esc, or 'h'
        if self.in_playlist_name and ch in (127, 8, 27, ord('h'), ord('H'), curses.KEY_BACKSPACE):
            self._exit_playlist_view()
            return

        # Direct tab switching: 1-6
        if ch in (ord('1'), ord('2'), ord('3'), ord('4'), ord('5'), ord('6')):
            idx = ch - ord('1')
            self._switch_tab(idx)
            return
        elif ch == 9:  # Tab key
            self._switch_tab((self.current_tab + 1) % len(TAB_NAMES))
            return
        elif ch == curses.KEY_BTAB:  # Shift-Tab
            self._switch_tab((self.current_tab - 1) % len(TAB_NAMES))
            return

        # Quick switch to Queue tab with 'u'
        elif ch in (ord('u'), ord('U')):
            self._switch_tab(TAB_QUEUE)
            return

        # Up / Down / PageUp / PageDown / j / k
        if ch in (curses.KEY_UP, ord('k'), ord('K')):
            self._move_selection(-1)
        elif ch in (curses.KEY_DOWN, ord('j'), ord('J')):
            self._move_selection(1)
        elif ch == curses.KEY_PPAGE:
            self._move_selection(-10)
        elif ch == curses.KEY_NPAGE:
            self._move_selection(10)

        # Fast Forward / Rewind: Left/Right Arrow (5s), Shift+Left/Shift+Right or [/] (30s)
        elif ch in (curses.KEY_RIGHT, ord('l'), ord('L')):
            if self.ipc:
                self.ipc.send_command(["seek", 5, "relative"])
                self.time_pos = min(self.duration, self.time_pos + 5)
                self.status_msg = "Fast Forward +5s (→)"
        elif ch in (curses.KEY_LEFT, ord('h'), ord('H')):
            if self.ipc:
                self.ipc.send_command(["seek", -5, "relative"])
                self.time_pos = max(0.0, self.time_pos - 5)
                self.status_msg = "Rewind -5s (←)"
        elif ch in (ord(']'), curses.KEY_SRIGHT):
            if self.ipc:
                self.ipc.send_command(["seek", 30, "relative"])
                self.time_pos = min(self.duration, self.time_pos + 30)
                self.status_msg = "Fast Forward +30s (])"
        elif ch in (ord('['), curses.KEY_SLEFT):
            if self.ipc:
                self.ipc.send_command(["seek", -30, "relative"])
                self.time_pos = max(0.0, self.time_pos - 30)
                self.status_msg = "Rewind -30s ([)"

        # Enter / Return -> Activate
        elif ch in (10, 13, curses.KEY_ENTER):
            self._activate_selected()

        # Play entire playlist directly: Shift+P
        elif ch in (ord('P'),):
            self._play_playlist_direct()

        # Space -> Pause / Resume
        elif ch == ord(' '):
            self.toggle_pause()

        # Search / Save
        elif ch == ord('/'):
            self._prompt_search()
        elif ch in (ord('s'), ord('S')):
            self._save_selected()

        # Remove / Skip song from upcoming radio queue: 'd', 'D', or Delete
        elif ch in (ord('d'), ord('D'), curses.KEY_DC):
            self._remove_selected_from_queue()

        # Radio force trigger
        elif ch in (ord('r'), ord('R')):
            self._start_radio_selected()

        # Cycle playback mode & manage live handoff
        elif ch in (ord('m'), ord('M')):
            self._handle_mode_switch()

        # Skip Next: '>' or '.' or 'n' or 'N'
        elif ch in (ord('>'), ord('.'), ord('n'), ord('N')):
            if self.dj_player and self.mode_idx in (1, 3):
                self.dj_player.skip_to_next = True
                self.status_msg = "Skipped to next track (>)."
            elif self.ipc:
                self.ipc.send_command(["playlist-next"])
                self.status_msg = "Skipped to next track (>)."

        # Skip Previous: '<' or ',' or 'p' or 'P'
        elif ch in (ord('<'), ord(','), ord('p'), ord('P')):
            if self.dj_player and self.mode_idx in (1, 3):
                self.dj_player.skip_to_prev = True
                self.status_msg = "Skipped to previous track (<)."
            elif self.ipc:
                self.ipc.send_command(["playlist-prev"])
                self.status_msg = "Skipped to previous track (<)."

        # Volume: 9/0 (mpv standard) as well as +/-
        elif ch in (ord('0'), ord('+'), ord('=')):
            if self.ipc:
                self.ipc.adjust_volume(5)
                self.status_msg = "Volume +5%"
        elif ch in (ord('9'), ord('-'), ord('_')):
            if self.ipc:
                self.ipc.adjust_volume(-5)
                self.status_msg = "Volume -5%"

        # Stop
        elif ch in (ord('x'), ord('X')):
            self.stop_playback()
            self.status_msg = "Playback stopped."

    def _handle_mode_switch(self):
        """Cycle playback mode and manage live handoff between Direct and DJ engines."""
        self.mode_idx = (self.mode_idx + 1) % len(MODES)
        mode_label = MODE_LABELS[self.mode_idx]
        is_dj_mode = self.mode_idx in (1, 3)

        if not self.now_playing:
            self.status_msg = f"Playback mode: {mode_label}"
            return

        if is_dj_mode:
            if self.dj_player:
                self.dj_player.light_mix = (self.mode_idx == 1)
                self.status_msg = f"🎛️ Switched to {mode_label}"
            else:
                # Direct mode -> DJ mode: Keep current song playing!
                self.pending_dj_handoff = True
                self.status_msg = f"🎛️ Switched to {mode_label}: Song continuing, DJ engine warming up for handoff..."

                # Prefetch next track in background so boundary has zero delay
                def warm_up():
                    next_idx = self.current_queue_idx + 1
                    if 0 <= next_idx < len(self.queue_tracks):
                        target_path = self.cache_mgr.get_track_cache_path(next_idx, "opus")
                        if not self.cache_mgr.track_is_cached(next_idx):
                            self.downloader.download_track(self.queue_tracks[next_idx], target_path)
                threading.Thread(target=warm_up, daemon=True).start()
        else:
            if self.dj_player:
                self.pending_dj_handoff = False
                self.status_msg = f"Switched to {mode_label}: Current song continuing, switching mode on next track..."
            else:
                self.status_msg = f"Switched mode to: {mode_label}"

    def _switch_tab(self, new_tab: int):
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
            if self.current_queue_idx >= 0 and self.current_queue_idx < len(self.items):
                self.selected_idx = self.current_queue_idx
                self.scroll_offset = max(0, self.selected_idx - 5)

        elif new_tab == TAB_SEARCH:
            self.items = list(self.search_results)
            if not self.items and not self.search_query:
                self.status_msg = "Press '/' to search YouTube Music catalog."

        elif new_tab == TAB_LOGIN:
            self._build_login_items()

    def _move_selection(self, delta: int):
        if not self.items:
            return
        new_idx = self.selected_idx + delta
        self.selected_idx = max(0, min(new_idx, len(self.items) - 1))

    def _activate_selected(self):
        if not self.items or self.selected_idx >= len(self.items):
            return

        item = self.items[self.selected_idx]

        if self.current_tab == TAB_LOGIN:
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
            return

        if self.current_tab == TAB_QUEUE and isinstance(item, Track):
            # Jump directly to track in the active queue
            target_idx = self.selected_idx
            if self.dj_player:
                self.stop_playback(keep_queue=True)
                self.current_queue_idx = target_idx
                self.play_track_and_start_radio(item, existing_queue=self.queue_tracks[target_idx:])
            elif self.ipc:
                self.ipc.set_property("playlist-pos", target_idx)
                self.current_queue_idx = target_idx
                self.now_playing = item.display_title()
                self._update_next_track()
                self.status_msg = f"Jumped to: {item.display_title()}"
            return

        if isinstance(item, Track):
            self.play_track_and_start_radio(item)

        elif isinstance(item, dict) and item.get("type") == "playlist":
            pl_id = item.get("id")
            title = item.get("title", "Playlist")
            self._open_playlist_drilldown(pl_id, title)

        elif isinstance(item, tuple) and item[0] == "saved":
            _, name, url = item
            self._play_external_target(url, f"Saved: {name}")

    def play_track_and_start_radio(self, track: Track, existing_queue: Optional[List[Track]] = None):
        """
        Play track immediately in MPV or DJPlayer and automatically queue its radio recommendations.
        """
        self.stop_playback(keep_queue=False)
        self.now_playing = track.display_title()
        self.next_playing = "Loading radio queue..." if not existing_queue else (existing_queue[1].display_title() if len(existing_queue) > 1 else None)
        self.is_paused = False
        self.time_pos = 0.0
        self.duration = track.duration_sec
        self.status_msg = f"▶ Playing: {track.display_title()} | Queuing radio..."

        is_dj_mode = self.mode_idx in (1, 3)

        if existing_queue:
            self.queue_tracks = list(existing_queue)
            self.current_queue_idx = 0
        else:
            self.queue_tracks = [track]
            self.current_queue_idx = 0

        if is_dj_mode:
            is_light = (self.mode_idx == 1)
            self.dj_player = DJPlayer(
                tracks=self.queue_tracks,
                cache_manager=self.cache_mgr,
                downloader=self.downloader,
                light_mix=is_light,
                crossfade_sec=DEFAULT_CROSSFADE_SEC,
                on_track_change=self._on_dj_track_change,
                custom_socket=SOCKET_PATH,
            )
            self.dj_player.start()
        else:
            self._ensure_mpv(raw_pcm_mode=False)
            if self.ipc:
                self.ipc.load_file(track.web_url, mode="replace")
                if existing_queue and len(existing_queue) > 1:
                    for t in existing_queue[1:]:
                        self.ipc.load_file(t.web_url, mode="append")

        # Asynchronously fetch radio if existing_queue wasn't provided
        if not existing_queue:
            track_id = track.id

            def worker():
                radio_tracks = self.client.get_watch_playlist_tracks(track_id, limit=35)
                if radio_tracks:
                    # Deduplicate against seed track
                    filtered = [t for t in radio_tracks if t.id != track_id]
                    self.queue_tracks.extend(filtered)
                    if self.dj_player:
                        self.dj_player.append_tracks(filtered)
                    elif self.ipc:
                        for t in filtered:
                            self.ipc.load_file(t.web_url, mode="append")

                    self._update_next_track()
                    self.status_msg = f"▶ Playing: {track.display_title()} | 📻 Radio: {len(filtered)} tracks queued"

                    if self.current_tab == TAB_QUEUE:
                        self.items = list(self.queue_tracks)
                else:
                    self.next_playing = None
                    self.status_msg = f"▶ Playing: {track.display_title()}"

            threading.Thread(target=worker, daemon=True).start()

    def _on_dj_track_change(self, idx: int, track: Track, transition: str = ""):
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

    def _update_next_track(self):
        """Update next_playing label based on queue position."""
        next_idx = self.current_queue_idx + 1
        if 0 <= next_idx < len(self.queue_tracks):
            self.next_playing = self.queue_tracks[next_idx].display_title()
        else:
            self.next_playing = None

    def _open_playlist_drilldown(self, playlist_id: str, title: str):
        """Fetch tracks inside a playlist and view them interactively."""
        self.is_loading = True
        self.loading_text = f"Opening '{title}'..."
        self.playlist_back_items = list(self.items)
        self.playlist_back_selected = self.selected_idx
        self.in_playlist_name = title

        def worker():
            tracks = self.client.get_playlist_tracks(playlist_id)
            self.is_loading = False
            if tracks:
                self.items = tracks
                self.selected_idx = 0
                self.scroll_offset = 0
                self.status_msg = f"Opened '{title}' ({len(tracks)} tracks). Press Enter to play track, Backspace to exit."
            else:
                self.status_msg = f"Could not load tracks for '{title}'."
                self.in_playlist_name = None
                self.items = self.playlist_back_items

        threading.Thread(target=worker, daemon=True).start()

    def _exit_playlist_view(self):
        if self.playlist_back_items:
            self.items = self.playlist_back_items
            self.selected_idx = self.playlist_back_selected
            self.scroll_offset = max(0, self.selected_idx - 5)
        self.in_playlist_name = None
        self.status_msg = "Back to playlists."

    def _play_playlist_direct(self):
        """Play entire playlist: load track 1 and queue the rest."""
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if isinstance(item, dict) and item.get("type") == "playlist":
            pl_id = item.get("id")
            title = item.get("title", "Playlist")
            self.status_msg = f"Queuing playlist '{title}'..."

            def worker():
                tracks = self.client.get_playlist_tracks(pl_id)
                if tracks:
                    first = tracks[0]
                    self.play_track_and_start_radio(first, existing_queue=tracks)
                    self.status_msg = f"▶ Playing '{title}' ({len(tracks)} tracks queued)"
                else:
                    self.status_msg = f"Could not load playlist '{title}'."

            threading.Thread(target=worker, daemon=True).start()

    def _play_external_target(self, target: str, title: str):
        """Fallback to direct MPV playback for custom target URLs."""
        self._ensure_mpv(raw_pcm_mode=False)
        if self.ipc:
            self.ipc.load_file(target, mode="replace")

    def _remove_selected_from_queue(self):
        """Remove/skip selected song from upcoming radio queue."""
        if not self.queue_tracks:
            self.status_msg = "Queue is empty."
            return

        # Determine target index in queue: if on Queue tab, use selected_idx, else target next upcoming track
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
            if self.dj_player:
                self.dj_player.skip_to_next = True
            elif self.ipc:
                self.ipc.send_command(["playlist-next"])
            del self.queue_tracks[target_idx]
            self.status_msg = f"Removed currently playing '{title[:25]}' and advanced."
        else:
            if self.ipc and not self.dj_player:
                self.ipc.send_command(["playlist-remove", target_idx])
            del self.queue_tracks[target_idx]
            if target_idx < self.current_queue_idx:
                self.current_queue_idx -= 1
            self.status_msg = f"Removed '{title[:25]}' from radio queue (d)."

        self._update_next_track()
        if self.current_tab == TAB_QUEUE:
            self.items = list(self.queue_tracks)
            self.selected_idx = min(self.selected_idx, max(0, len(self.items) - 1))

    def _start_radio_selected(self):
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if isinstance(item, Track):
            self.play_track_and_start_radio(item)

    def _save_selected(self):
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if isinstance(item, Track):
            self.status_msg = f"Downloading '{item.display_title()}' to ~/Music..."

            def worker():
                save_dir = os.path.expanduser("~/Music")
                os.makedirs(save_dir, exist_ok=True)
                target = os.path.join(save_dir, f"{item.title}.opus")
                ok = self.downloader.download_track(item, target)
                self.status_msg = f"Saved '{item.title}' to ~/Music" if ok else f"Failed to save '{item.title}'"

            threading.Thread(target=worker, daemon=True).start()

    def _prompt_search(self):
        """Open curses line-input prompt to search YouTube Music."""
        curses.echo()
        curses.curs_set(1)
        max_y, max_x = self.stdscr.getmaxyx()
        self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1))
        self.stdscr.addstr(max_y - 1, 0, "🔍 Search YouTube Music: ", curses.A_BOLD | curses.color_pair(5))
        self.stdscr.refresh()

        try:
            query_bytes = self.stdscr.getstr(max_y - 1, 25, 60)
            query = query_bytes.decode("utf-8").strip()
        except Exception:
            query = ""

        curses.noecho()
        curses.curs_set(0)

        if query:
            self.search_query = query
            self._switch_tab(TAB_SEARCH)
            self.is_loading = True
            self.loading_text = f"Searching for '{query}'..."

            def worker():
                results = self.client.search(query, limit=25)
                self.is_loading = False
                self.search_results = results
                if self.current_tab == TAB_SEARCH:
                    self.items = list(results)
                    self.selected_idx = 0
                    self.scroll_offset = 0
                    self.status_msg = f"Found {len(results)} search results for '{query}'."

            threading.Thread(target=worker, daemon=True).start()
        else:
            self.status_msg = "Search cancelled."

    def _build_login_items(self):
        is_auth = self.auth_mgr.is_authenticated()
        self.items = [
            {"title": "⚡ 1-Click Auto-Detect Login (Zen, Chrome, Firefox...)", "action": "auto_login", "desc": "Imports session cookies from installed browser profiles automatically"},
            {"title": "🦊 1-Click Zen Browser Login", "action": "zen_login", "desc": "Directly extract authenticated YouTube cookies from Zen profile"},
            {"title": "🌐 Open https://music.youtube.com in Browser", "action": "open_browser", "desc": "Launch browser so you can log into your Google Account"},
        ]
        if is_auth:
            self.items.append({"title": "🚪 Log Out / Clear Saved Credentials", "action": "logout", "desc": "Delete cached headers and reset to anonymous session"})

    def _run_browser_login_async(self, browser_name: str):
        self.is_loading = True
        self.loading_text = f"Importing session cookies ({browser_name})..."

        def worker():
            ok = self.auth_mgr.setup_from_browser(browser_name)
            self.is_loading = False
            if ok:
                self.client._init_ytm()
                self.status_msg = "Successfully authenticated with YouTube Music! Reloading library..."
                self.fetch_recommended_async()
                self.fetch_playlists_async()
            else:
                self.status_msg = f"Could not extract cookies from {browser_name}. Ensure you are logged into YouTube in that browser."

        threading.Thread(target=worker, daemon=True).start()

    def fetch_recommended_async(self):
        self.is_loading = True
        self.loading_text = "Fetching personalized recommendations..."

        def worker():
            sections = self.client.get_personalized_feed()
            self.is_loading = False
            if sections:
                self.recommended_sections = sections
                if self.current_tab == TAB_RECOMMENDED:
                    self._rebuild_items_from_sections(sections)
                    self.status_msg = f"Loaded {len(sections)} personalized sections."
            else:
                self.status_msg = "Could not fetch recommendations. Check your network or login."

        threading.Thread(target=worker, daemon=True).start()

    def _rebuild_items_from_sections(self, sections: List[Dict[str, Any]]):
        flattened: List[Any] = []
        for sec in sections:
            title = sec.get("title", "Section")
            items = sec.get("items", [])
            if items:
                flattened.append({"type": "section_header", "title": title})
                flattened.extend(items)
        self.items = flattened
        self.selected_idx = 1 if len(flattened) > 1 else 0

    def fetch_playlists_async(self):
        self.is_loading = True
        self.loading_text = "Fetching library playlists..."

        def worker():
            playlists = self.client.get_user_playlists()
            self.is_loading = False
            self.my_playlists = playlists
            if self.current_tab == TAB_PLAYLISTS:
                self.items = list(playlists)
                self.status_msg = f"Loaded {len(playlists)} library playlists."

        threading.Thread(target=worker, daemon=True).start()

    def fetch_liked_async(self):
        self.is_loading = True
        self.loading_text = "Fetching Liked Songs..."

        def worker():
            tracks = self.client.get_liked_songs(limit=100)
            self.is_loading = False
            self.liked_tracks = tracks
            if self.current_tab == TAB_LIKED:
                self.items = list(tracks)
                self.status_msg = f"Loaded {len(tracks)} liked tracks."

        threading.Thread(target=worker, daemon=True).start()

    def _load_saved_playlists(self):
        if not self.saved_local_playlists and os.path.exists(PLAYLIST_FILE):
            try:
                with open(PLAYLIST_FILE, "r") as f:
                    for line in f:
                        parts = line.strip().split("|", 1)
                        if len(parts) == 2:
                            self.saved_local_playlists.append((parts[0].strip(), parts[1].strip()))
            except Exception:
                pass

    def toggle_pause(self):
        if self.dj_player:
            self.dj_player.toggle_pause = True
            self.is_paused = not self.is_paused
            self.status_msg = "Paused." if self.is_paused else "Resumed."
        elif self.ipc and os.path.exists(SOCKET_PATH):
            self.ipc.cycle_pause()
            self.is_paused = not self.is_paused
            self.status_msg = "Paused." if self.is_paused else "Resumed."

    def stop_playback(self, keep_queue: bool = False):
        if self.dj_player:
            try:
                self.dj_player.stop()
            except Exception:
                pass
            self.dj_player = None

        if self.ipc and os.path.exists(SOCKET_PATH):
            try:
                self.ipc.stop()
            except Exception:
                pass

        if self.mpv_process:
            try:
                self.mpv_process.terminate()
            except Exception:
                pass
            self.mpv_process = None

        if not keep_queue:
            self.now_playing = None
            self.next_playing = None
            self.queue_tracks = []
            self.current_queue_idx = -1
            self.is_paused = False
            self.time_pos = 0.0
            self.duration = 0.0

    def _update_playback_status(self):
        if not os.path.exists(SOCKET_PATH):
            return

        if self.dj_player and self.mode_idx in (1, 3):
            # DJ Mode active
            st = self.dj_player.get_playback_status()
            self.time_pos = st["time_pos"]
            self.duration = st["duration"]
            self.is_paused = st["is_paused"]
            if st["track"]:
                self.now_playing = st["track"].display_title()
                self.current_queue_idx = st["index"]
                self._update_next_track()
                if st.get("transition"):
                    self.status_msg = f"▶ Playing: {self.now_playing} | 🎛️ Auto-DJ: {st['transition']}"
                if self.current_tab == TAB_QUEUE:
                    self.items = list(self.queue_tracks)
            return

        # Direct MPV mode
        try:
            t = self.ipc.get_property("time-pos")
            d = self.ipc.get_property("duration")
            p = self.ipc.get_property("pause")
            pos = self.ipc.get_property("playlist-pos")

            if t is not None:
                self.time_pos = float(t)
            if d is not None:
                self.duration = float(d)
            if p is not None:
                self.is_paused = bool(p)

            # Auto-detect track advancement in MPV's queue
            if pos is not None and isinstance(pos, int) and pos >= 0:
                if pos != self.current_queue_idx and pos < len(self.queue_tracks):
                    self.current_queue_idx = pos
                    current_track = self.queue_tracks[pos]
                    self.now_playing = current_track.display_title()
                    self._update_next_track()
                    if self.current_tab == TAB_QUEUE:
                        self.items = list(self.queue_tracks)

            # Check for pending DJ handoff as current track nears its end
            if self.pending_dj_handoff and self.duration > 0:
                remaining = self.duration - self.time_pos
                next_idx = self.current_queue_idx + 1
                if remaining <= 4.0 and next_idx < len(self.queue_tracks):
                    self.pending_dj_handoff = False
                    next_track = self.queue_tracks[next_idx]
                    self.status_msg = f"🎛️ Auto-DJ handoff: Transitioning to {next_track.display_title()}..."
                    # Seamlessly hand off to DJ engine with remaining queue
                    self.stop_playback(keep_queue=True)
                    self.current_queue_idx = next_idx
                    self.play_track_and_start_radio(next_track, existing_queue=self.queue_tracks[next_idx:])
        except Exception:
            pass

    def _draw(self):
        """Render the complete TUI screen."""
        self.stdscr.erase()
        max_y, max_x = self.stdscr.getmaxyx()
        if max_y < 12 or max_x < 40:
            self.stdscr.addstr(0, 0, "Terminal too small!")
            self.stdscr.refresh()
            return

        # 1. Header Bar
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

        # 2. Tabs Row or Drill-down Breadcrumb
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

        # 3. Separator
        self.stdscr.addstr(2, 0, "─" * (max_x - 1), curses.color_pair(6))

        # 4. Content Area
        content_top = 3
        content_bottom = max_y - 4
        content_height = content_bottom - content_top

        if self.is_loading:
            loading_msg = f"⏳ {self.loading_text}"
            self.stdscr.addstr(content_top + 2, max(0, (max_x - len(loading_msg)) // 2), loading_msg, curses.color_pair(5) | curses.A_BOLD)

        elif not self.items:
            empty_msg = "No items available. Press '1' to refresh or '6' to login."
            if self.current_tab == TAB_SEARCH and not self.search_query:
                empty_msg = "Press '/' to search YouTube Music tracks and albums."
            self.stdscr.addstr(content_top + 2, max(0, (max_x - len(empty_msg)) // 2), empty_msg, curses.color_pair(6))

        else:
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
                    line_str = f"── {item.get('title')} ──"
                    attr = curses.A_BOLD | curses.color_pair(4)
                elif isinstance(item, Track):
                    prefix = " ▶ " if self.now_playing and item.title in self.now_playing else "   "
                    line_str = f"{prefix}{item.display_title()}"
                    attr = curses.color_pair(2) if is_sel else (curses.color_pair(3) if "▶" in prefix else curses.color_pair(6))
                elif isinstance(item, dict) and item.get("type") == "playlist":
                    line_str = f" 📁 {item.get('title', 'Playlist')} ({item.get('count', '?')} tracks)"
                    attr = curses.color_pair(2) if is_sel else curses.color_pair(4)
                elif isinstance(item, dict) and "action" in item:
                    line_str = f" {item.get('title')} — {item.get('desc')}"
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

        # 5. Playback Bar (Above Bottom Separator)
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

        # 6. Controls Footer
        footer_y = max_y - 1
        footer_str = " [Enter] Play/Drill  [Space] Pause  [←/→] Seek  [>/<] Skip  [d] Drop  [r] Radio  [m] Mode  [/] Search  [q] Quit "
        self.stdscr.addstr(footer_y, 0, footer_str[:max_x - 1], curses.A_REVERSE | curses.color_pair(4))

        self.stdscr.refresh()

    def _render_progress_bar(self, width: int = 20) -> str:
        if self.duration <= 0:
            return " " * width
        ratio = min(1.0, max(0.0, self.time_pos / self.duration))
        filled = int(ratio * width)
        if filled > 0:
            return "=" * (filled - 1) + ">" + "-" * (width - filled)
        return "-" * width

    def _fmt_sec(self, sec: float) -> str:
        s = int(sec)
        m = s // 60
        s = s % 60
        return f"{m:02d}:{s:02d}"

    def run(self):
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
            elif ch != -1:
                self._handle_input(ch)

        self.cleanup()


def main():
    try:
        curses.wrapper(lambda stdscr: TUIApp(stdscr).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
