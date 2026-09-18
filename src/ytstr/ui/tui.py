"""
Terminal User Interface (TUI) for YouTube Music and ytstr.
Built using standard library curses for zero-dependency, ultra-lightweight performance.
"""
import curses
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ytstr.config import PLAYLIST_FILE, VERSION
from ytstr.core.types import Track
from ytstr.playback.mpv_ipc import MPVIPCClient
from ytstr.ytm.auth import AuthManager
from ytstr.ytm.client import YouTubeMusicClient

SOCKET_PATH = "/tmp/ytstr_tui_mpv.sock"

TAB_RECOMMENDED = 0
TAB_PLAYLISTS = 1
TAB_LIKED = 2
TAB_SEARCH = 3
TAB_LOGIN = 4
TAB_NAMES = ["🎵 Recommended", "📁 My Playlists", "❤️ Liked Songs", "🔍 Search", "🔑 Account"]

MODES = ["--no-mix", "--light-mix", "--stream", ""]
MODE_LABELS = ["Direct Low-RAM", "Light Mix", "Direct Stream", "Auto-DJ (Spectral)"]


class TUIApp:
    """Terminal User Interface for personalized YouTube Music streaming."""

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.auth_mgr = AuthManager()
        self.client = YouTubeMusicClient(self.auth_mgr)

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
        self.search_results: List[Track] = []
        self.saved_local_playlists: List[Tuple[str, str]] = []

        # Playback status
        self.player_proc: Optional[subprocess.Popen] = None
        self.ipc = MPVIPCClient(SOCKET_PATH)
        self.now_playing: Optional[str] = None
        self.is_paused = False
        self.time_pos = 0.0
        self.duration = 0.0
        self.status_msg = "Ready. Select a track or playlist to play. Press ? for help."

        # Loading & thread state
        self.is_loading = False
        self.loading_text = ""
        self.search_query = ""

        self._setup_curses()
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

    def run(self):
        """Main event loop."""
        while True:
            self._update_playback_status()
            self._draw()

            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue

            if ch == -1:
                continue

            if ch in (ord('q'), ord('Q')):
                if self.in_playlist_name:
                    self._exit_playlist_view()
                    continue
                self.stop_playback()
                break

            self._handle_input(ch)

    def _handle_input(self, ch: int):
        # Back navigation from playlist drill-down: Backspace (127/8), Esc (27), or 'h'
        if self.in_playlist_name and ch in (127, 8, 27, ord('h'), ord('H'), curses.KEY_BACKSPACE):
            self._exit_playlist_view()
            return

        # Tab navigation: 1-5 or Tab
        if ch in (ord('1'), ord('2'), ord('3'), ord('4'), ord('5')):
            idx = ch - ord('1')
            self._switch_tab(idx)
            return
        elif ch == 9:  # Tab key
            self._switch_tab((self.current_tab + 1) % len(TAB_NAMES))
            return
        elif ch == curses.KEY_BTAB:  # Shift-Tab
            self._switch_tab((self.current_tab - 1) % len(TAB_NAMES))
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

        # Enter / Return -> Activate
        elif ch in (10, 13, curses.KEY_ENTER):
            self._activate_selected()

        # Play whole playlist directly without drilldown (Shift+P)
        elif ch == ord('P'):
            self._play_playlist_direct()

        # Space -> Pause / Resume
        elif ch == ord(' '):
            self.toggle_pause()

        # Search / Save
        elif ch == ord('/'):
            self._prompt_search()
        elif ch in (ord('s'), ord('S')):
            self._save_selected()

        # Radio
        elif ch in (ord('r'), ord('R')):
            self._start_radio_selected()

        # Cycle playback mode
        elif ch in (ord('m'), ord('M')):
            self.mode_idx = (self.mode_idx + 1) % len(MODES)
            self.status_msg = f"Switched mode to: {MODE_LABELS[self.mode_idx]}"

        # Skip Next / Previous
        elif ch in (ord('n'), ord('N')):
            if self.player_proc:
                self.ipc.send_command(["playlist-next"])
        elif ch in (ord('p'), ord('P')):
            if self.player_proc:
                self.ipc.send_command(["playlist-prev"])

        # Volume
        elif ch in (ord('+'), ord('=')):
            if self.player_proc:
                self.ipc.adjust_volume(5)
                self.status_msg = "Volume +5%"
        elif ch in (ord('-'), ord('_')):
            if self.player_proc:
                self.ipc.adjust_volume(-5)
                self.status_msg = "Volume -5%"

        # Stop
        elif ch in (ord('x'), ord('X')):
            self.stop_playback()
            self.status_msg = "Playback stopped."

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

        elif new_tab == TAB_SEARCH:
            self.items = list(self.search_results)

        elif new_tab == TAB_LOGIN:
            self._build_login_items()

    def _move_selection(self, delta: int):
        if not self.items:
            return
        new_idx = max(0, min(len(self.items) - 1, self.selected_idx + delta))
        if isinstance(self.items[new_idx], str) and self.items[new_idx].startswith("---"):
            new_idx = max(0, min(len(self.items) - 1, new_idx + (1 if delta >= 0 else -1)))
        self.selected_idx = new_idx

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

        if isinstance(item, Track):
            self.play_target(item.web_url, item.display_title())

        elif isinstance(item, dict) and item.get("type") == "playlist":
            pl_id = item.get("id")
            title = item.get("title", "Playlist")
            self._open_playlist_drilldown(pl_id, title)

        elif isinstance(item, tuple) and item[0] == "saved":
            _, name, url = item
            self.play_target(url, f"Saved: {name}")

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
        """Play entire playlist without entering drilldown."""
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if isinstance(item, dict) and item.get("type") == "playlist":
            url = f"https://www.youtube.com/playlist?list={item.get('id')}"
            self.play_target(url, f"Playlist: {item.get('title')}")

    def _start_radio_selected(self):
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if not isinstance(item, Track):
            self.status_msg = "Radio is available for individual tracks."
            return

        self.status_msg = f"Fetching radio for '{item.title}'..."
        track_id = item.id

        def worker():
            tracks = self.client.get_watch_playlist_tracks(track_id, limit=30)
            if tracks:
                self.search_results = tracks
                self.items = tracks
                self.selected_idx = 0
                self.current_tab = TAB_SEARCH
                self.play_target(item.web_url, f"Radio: {item.title}")
            else:
                self.status_msg = "Could not fetch radio tracks."

        threading.Thread(target=worker, daemon=True).start()

    def _save_selected(self):
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        title = ""
        url = ""
        if isinstance(item, Track):
            title = item.display_title()
            url = item.web_url
        elif isinstance(item, dict) and item.get("type") == "playlist":
            title = item.get("title", "Playlist")
            url = f"https://www.youtube.com/playlist?list={item.get('id')}"

        if title and url:
            try:
                with open(PLAYLIST_FILE, "a", encoding="utf-8") as f:
                    f.write(f"{title}|{url}\n")
                self.status_msg = f"Saved '{title}' to playlists!"
            except Exception as e:
                self.status_msg = f"Failed to save: {e}"

    def _prompt_search(self):
        curses.curs_set(1)
        self.stdscr.nodelay(False)
        max_y, max_x = self.stdscr.getmaxyx()
        prompt = "🔍 Search YouTube Music: "
        self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1))
        self.stdscr.addstr(max_y - 1, 0, prompt, curses.A_BOLD | curses.color_pair(4))
        self.stdscr.refresh()

        curses.echo()
        raw = self.stdscr.getstr(max_y - 1, len(prompt), max_x - len(prompt) - 2)
        curses.noecho()
        curses.curs_set(0)
        self.stdscr.nodelay(True)

        query = raw.decode("utf-8", errors="ignore").strip()
        if not query:
            return

        self.search_query = query
        self.current_tab = TAB_SEARCH
        self.in_playlist_name = None
        self.is_loading = True
        self.loading_text = f"Searching for '{query}'..."
        self.items = []

        def worker():
            try:
                tracks = self.client.search_tracks(query, limit=30)
                self.search_results = tracks
                self.items = tracks
                self.selected_idx = 0
                self.status_msg = f"Found {len(tracks)} tracks for '{query}'."
            except Exception as e:
                self.status_msg = f"Search failed: {e}"
            finally:
                self.is_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def fetch_recommended_async(self):
        self.is_loading = True
        self.loading_text = "Loading personalized recommendations (Listen Again, Quick Picks)..."
        self.items = []

        def worker():
            try:
                sections = self.client.get_home_sections(limit=10, personalized_only=True)
                self.recommended_sections = sections
                if self.current_tab == TAB_RECOMMENDED:
                    self._rebuild_items_from_sections(sections)
                self.status_msg = f"Loaded {len(sections)} personalized music sections."
            except Exception as e:
                self.status_msg = f"Failed to load recommendations: {e}"
            finally:
                self.is_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def fetch_playlists_async(self):
        self.is_loading = True
        self.loading_text = "Loading your YouTube Music playlists..."
        self.items = []

        def worker():
            try:
                lib_pls = self.client.get_library_playlists(limit=50)
                self.load_local_playlists()
                combined: List[Any] = []

                if lib_pls:
                    for p in lib_pls:
                        combined.append(p)

                if self.saved_local_playlists:
                    combined.append("--- 💾 LOCAL SAVED PLAYLISTS ---")
                    for name, url in self.saved_local_playlists:
                        combined.append(("saved", name, url))

                self.my_playlists = combined
                if self.current_tab == TAB_PLAYLISTS and not self.in_playlist_name:
                    self.items = combined
                self.status_msg = f"Loaded {len(lib_pls)} library playlists."
            except Exception as e:
                self.status_msg = f"Failed to load playlists: {e}"
            finally:
                self.is_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def fetch_liked_async(self):
        self.is_loading = True
        self.loading_text = "Loading your Liked Music..."
        self.items = []

        def worker():
            try:
                tracks = self.client.get_liked_songs(limit=100)
                self.liked_tracks = tracks
                if self.current_tab == TAB_LIKED:
                    self.items = tracks
                self.status_msg = f"Loaded {len(tracks)} liked songs."
            except Exception as e:
                self.status_msg = f"Failed to load liked songs: {e}"
            finally:
                self.is_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def _run_browser_login_async(self, browser_name: str):
        def worker():
            self.is_loading = True
            self.loading_text = f"Extracting session from {browser_name}..."
            try:
                ok, msg = self.auth_mgr.import_cookies_from_browser(browser_name)
                if ok:
                    self.status_msg = f"✓ {msg}"
                    self.client._init_ytm()
                    self.fetch_playlists_async()
                    self.fetch_recommended_async()
                else:
                    self.status_msg = f"Login Note: {msg}"
            except Exception as e:
                self.status_msg = f"Login Error: {e}"
            finally:
                self.is_loading = False
                self._build_login_items()

        threading.Thread(target=worker, daemon=True).start()

    def _build_login_items(self):
        is_auth = self.auth_mgr.is_authenticated()
        self.items = [
            {"label": "⚡ 1. Auto-Detect & Extract Session (Zen, Firefox, Chrome, Brave...)", "action": "auto_login"},
            {"label": "🦊 2. Extract Session specifically from Zen Browser", "action": "zen_login"},
            {"label": "🌐 3. Open music.youtube.com in Browser", "action": "open_browser"},
        ]
        if is_auth:
            self.items.append({"label": "🚪 4. Log Out (Clear Credentials)", "action": "logout"})

    def _rebuild_items_from_sections(self, sections: List[Dict[str, Any]]):
        flattened: List[Any] = []
        for sec in sections:
            sec_title = sec.get("title", "Section")
            items = sec.get("items", [])
            if not items:
                continue
            flattened.append(f"--- 🎵 {sec_title.upper()} ---")
            for item in items[:12]:
                flattened.append(item)
        self.items = flattened

    def load_local_playlists(self):
        self.saved_local_playlists = []
        if os.path.exists(PLAYLIST_FILE):
            try:
                with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "|" in line:
                            parts = line.split("|", 1)
                            self.saved_local_playlists.append((parts[0].strip(), parts[1].strip()))
            except Exception:
                pass

    def play_target(self, target: str, title: str):
        """Spawn ytstr playback engine in background with IPC socket."""
        self.stop_playback()
        self.now_playing = title
        self.is_paused = False
        self.time_pos = 0.0
        self.duration = 0.0

        mode_flag = MODES[self.mode_idx]
        cmd = [sys.executable, "-m", "ytstr", target]
        if mode_flag:
            cmd.append(mode_flag)
        cmd.extend(["--ipc-socket", SOCKET_PATH])

        try:
            self.player_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self.status_msg = f"▶ Playing: {title} [{MODE_LABELS[self.mode_idx]}]"
        except Exception as e:
            self.status_msg = f"Failed to launch playback: {e}"

    def toggle_pause(self):
        if self.player_proc and os.path.exists(SOCKET_PATH):
            self.ipc.cycle_pause()
            self.is_paused = not self.is_paused
            self.status_msg = "Paused." if self.is_paused else "Resumed."

    def stop_playback(self):
        if self.player_proc:
            try:
                self.player_proc.terminate()
            except Exception:
                pass
            self.player_proc = None
        self.now_playing = None
        self.is_paused = False
        self.time_pos = 0.0
        self.duration = 0.0

    def _update_playback_status(self):
        if self.player_proc and os.path.exists(SOCKET_PATH):
            try:
                t = self.ipc.get_property("time-pos")
                d = self.ipc.get_property("duration")
                p = self.ipc.get_property("pause")
                if t is not None:
                    self.time_pos = float(t)
                if d is not None:
                    self.duration = float(d)
                if p is not None:
                    self.is_paused = bool(p)
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
            self.stdscr.addstr(content_top + 2, max(2, (max_x - len(loading_msg)) // 2), loading_msg, curses.A_BOLD | curses.color_pair(5))
        elif not self.items:
            empty_msg = "No items to display. Check connection or switch tabs."
            self.stdscr.addstr(content_top + 2, max(2, (max_x - len(empty_msg)) // 2), empty_msg, curses.color_pair(5))
        else:
            if self.selected_idx < self.scroll_offset:
                self.scroll_offset = self.selected_idx
            elif self.selected_idx >= self.scroll_offset + content_height:
                self.scroll_offset = self.selected_idx - content_height + 1

            for row_idx in range(content_height):
                item_idx = self.scroll_offset + row_idx
                if item_idx >= len(self.items):
                    break

                item = self.items[item_idx]
                y = content_top + row_idx
                is_selected = (item_idx == self.selected_idx)

                if isinstance(item, str) and item.startswith("---"):
                    header_text = f" {item} "
                    self.stdscr.addstr(y, 1, header_text[:max_x - 2], curses.A_BOLD | curses.color_pair(1))

                elif isinstance(item, Track):
                    prefix = " ▶ " if is_selected else "   "
                    duration_str = ""
                    if item.duration_sec > 0:
                        m = int(item.duration_sec // 60)
                        s = int(item.duration_sec % 60)
                        duration_str = f"{m}:{s:02d}"

                    artist_str = item.artist or "YouTube"
                    line_avail = max_x - len(prefix) - len(duration_str) - 6
                    title_part = item.title[:max(10, line_avail // 2)]
                    artist_part = artist_str[:max(10, line_avail - len(title_part) - 2)]

                    line_content = f"{prefix}{title_part.ljust(len(title_part)+2)} {artist_part}"
                    if duration_str:
                        line_content = line_content.ljust(max_x - len(duration_str) - 3) + duration_str

                    attr = curses.color_pair(2) | curses.A_BOLD if is_selected else curses.color_pair(6)
                    self.stdscr.addstr(y, 0, line_content[:max_x - 1], attr)

                elif isinstance(item, dict) and item.get("type") == "playlist":
                    prefix = " ▶ 📁 " if is_selected else "   📁 "
                    title = item.get("title", "Playlist")
                    count = item.get("count")
                    count_str = f"({count} tracks)" if count else ""
                    line_content = f"{prefix}{title}  {count_str}".strip()
                    attr = curses.color_pair(2) | curses.A_BOLD if is_selected else curses.color_pair(4)
                    self.stdscr.addstr(y, 0, line_content[:max_x - 1], attr)

                elif isinstance(item, dict) and "label" in item:
                    prefix = " ▶ " if is_selected else "   "
                    line_content = f"{prefix}{item['label']}"
                    attr = curses.color_pair(2) | curses.A_BOLD if is_selected else curses.color_pair(6)
                    self.stdscr.addstr(y, 0, line_content[:max_x - 1], attr)

                elif isinstance(item, tuple) and item[0] == "saved":
                    prefix = " ▶ 📁 " if is_selected else "   📁 "
                    line_content = f"{prefix}{item[1]} [Saved]"
                    attr = curses.color_pair(2) | curses.A_BOLD if is_selected else curses.color_pair(4)
                    self.stdscr.addstr(y, 0, line_content[:max_x - 1], attr)

        # 5. Playback Bar
        bar_y = max_y - 3
        self.stdscr.addstr(bar_y, 0, "─" * (max_x - 1), curses.color_pair(6))

        play_icon = "⏸" if self.is_paused else "▶"
        if self.now_playing:
            cur_time = f"{int(self.time_pos // 60):02d}:{int(self.time_pos % 60):02d}"
            tot_time = f"{int(self.duration // 60):02d}:{int(self.duration % 60):02d}" if self.duration > 0 else "--:--"

            progress_bar_width = max(10, min(30, max_x - 45))
            ratio = min(1.0, max(0.0, (self.time_pos / self.duration))) if self.duration > 0 else 0.0
            filled = int(ratio * progress_bar_width)
            p_bar = f"[{'=' * filled}{'>' if filled < progress_bar_width else ''}{' ' * max(0, progress_bar_width - filled - 1)}]"

            play_info = f" {play_icon} {self.now_playing[:max(10, max_x - 45)]}  {p_bar} {cur_time}/{tot_time} "
            self.stdscr.addstr(bar_y + 1, 0, play_info[:max_x - 1], curses.A_BOLD | curses.color_pair(3))
        else:
            self.stdscr.addstr(bar_y + 1, 0, f" {self.status_msg}"[:max_x - 1], curses.color_pair(6))

        # 6. Footer / Keybindings
        footer_y = max_y - 1
        if self.in_playlist_name:
            footer = " [Enter] Play Track  [Backspace] Back to Playlists  [Space] Pause  [m] Mode  [q] Quit"
        else:
            footer = " [Tab] Tab  [Enter] Open/Play  [Shift+P] Play Playlist  [Space] Pause  [/] Search  [r] Radio  [m] Mode  [q] Quit"
        self.stdscr.addstr(footer_y, 0, footer[:max_x - 1], curses.A_REVERSE | curses.color_pair(6))

        self.stdscr.refresh()


def main():
    curses.wrapper(lambda stdscr: TUIApp(stdscr).run())


if __name__ == "__main__":
    main()
