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

TAB_HOME = 0
TAB_CHARTS = 1
TAB_SEARCH = 2
TAB_SAVED = 3
TAB_LOGIN = 4
TAB_NAMES = ["🏠 Home", "📈 Charts", "🔍 Search", "📁 Saved", "🔑 Login"]

MODES = ["--no-mix", "--light-mix", "--stream", ""]
MODE_LABELS = ["Direct Low-RAM", "Light Mix", "Direct Stream", "Auto-DJ (Spectral)"]


class TUIApp:
    """Terminal User Interface for browsing and streaming YouTube Music."""

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.auth_mgr = AuthManager()
        self.client = YouTubeMusicClient(self.auth_mgr)

        self.current_tab = TAB_HOME
        self.mode_idx = 0  # Default to Direct Low-RAM

        # Navigation & list items
        self.items: List[Any] = []  # Can contain Track, dict (playlist), or section header str
        self.selected_idx = 0
        self.scroll_offset = 0

        # Cached tab items
        self.home_sections: List[Dict[str, Any]] = []
        self.charts_sections: List[Dict[str, Any]] = []
        self.search_results: List[Track] = []
        self.saved_playlists: List[Tuple[str, str]] = []

        # Playback status
        self.player_proc: Optional[subprocess.Popen] = None
        self.ipc = MPVIPCClient(SOCKET_PATH)
        self.now_playing: Optional[str] = None
        self.is_paused = False
        self.time_pos = 0.0
        self.duration = 0.0
        self.status_msg = "Ready. Press Enter to play, / to search, ? for help."

        # Loading & thread state
        self.is_loading = False
        self.loading_text = ""
        self.search_query = ""

        self._setup_curses()
        self.load_saved_playlists()
        self.fetch_home_async()

    def _setup_curses(self):
        curses.curs_set(0)
        curses.use_default_colors()
        self.stdscr.timeout(200)  # 200ms non-blocking tick for progress bar updates

        # Initialize color pairs
        if curses.has_colors():
            curses.init_pair(1, curses.COLOR_RED, -1)     # Red accent / logo
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)  # Selected row
            curses.init_pair(3, curses.COLOR_GREEN, -1)   # Green / playing / active
            curses.init_pair(4, curses.COLOR_CYAN, -1)    # Playlist / category
            curses.init_pair(5, curses.COLOR_YELLOW, -1)  # Warnings / prompts
            curses.init_pair(6, curses.COLOR_WHITE, -1)   # Normal text

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
                self.stop_playback()
                break

            self._handle_input(ch)

    def _handle_input(self, ch: int):
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

        # Up / Down / PageUp / PageDown
        if ch in (curses.KEY_UP, ord('k'), ord('K')):
            self._move_selection(-1)
        elif ch in (curses.KEY_DOWN, ord('j'), ord('J')):
            self._move_selection(1)
        elif ch == curses.KEY_PPAGE:  # Page Up
            self._move_selection(-10)
        elif ch == curses.KEY_NPAGE:  # Page Down
            self._move_selection(10)

        # Actions
        elif ch in (10, 13, curses.KEY_ENTER):  # Enter key
            self._activate_selected()
        elif ch == ord(' '):  # Space -> Pause / Resume
            self.toggle_pause()
        elif ch in (ord('/'), ord('s')):
            if ch == ord('/'):
                self._prompt_search()
            else:
                self._save_selected()
        elif ch in (ord('r'), ord('R')):
            self._start_radio_selected()
        elif ch in (ord('m'), ord('M')):
            # Cycle playback mode
            self.mode_idx = (self.mode_idx + 1) % len(MODES)
            self.status_msg = f"Switched mode to: {MODE_LABELS[self.mode_idx]}"
        elif ch in (ord('n'), ord('N')):
            # Next track in mpv
            if self.player_proc:
                self.ipc.send_command(["playlist-next"])
        elif ch in (ord('p'), ord('P')):
            # Prev track in mpv
            if self.player_proc:
                self.ipc.send_command(["playlist-prev"])
        elif ch == ord('+') or ch == ord('='):
            if self.player_proc:
                self.ipc.adjust_volume(5)
                self.status_msg = "Volume +5%"
        elif ch == ord('-') or ch == ord('_'):
            if self.player_proc:
                self.ipc.adjust_volume(-5)
                self.status_msg = "Volume -5%"
        elif ch in (ord('x'), ord('X')):
            self.stop_playback()
            self.status_msg = "Playback stopped."

    def _switch_tab(self, new_tab: int):
        self.current_tab = new_tab
        self.selected_idx = 0
        self.scroll_offset = 0

        if new_tab == TAB_HOME:
            if not self.home_sections:
                self.fetch_home_async()
            else:
                self._rebuild_items_from_sections(self.home_sections)
        elif new_tab == TAB_CHARTS:
            if not self.charts_sections:
                self.fetch_charts_async()
            else:
                self._rebuild_items_from_sections(self.charts_sections)
        elif new_tab == TAB_SEARCH:
            self.items = list(self.search_results)
        elif new_tab == TAB_SAVED:
            self.load_saved_playlists()
            self.items = [("saved", name, url) for name, url in self.saved_playlists]
        elif new_tab == TAB_LOGIN:
            self._build_login_items()

    def _move_selection(self, delta: int):
        if not self.items:
            return
        new_idx = max(0, min(len(self.items) - 1, self.selected_idx + delta))
        # Skip section headers if landing on one
        if isinstance(self.items[new_idx], str) and self.items[new_idx].startswith("---"):
            new_idx = max(0, min(len(self.items) - 1, new_idx + (1 if delta >= 0 else -1)))
        self.selected_idx = new_idx

    def _activate_selected(self):
        if not self.items or self.selected_idx >= len(self.items):
            return

        item = self.items[self.selected_idx]

        if self.current_tab == TAB_LOGIN:
            # Login action items
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
            url = f"https://www.youtube.com/playlist?list={item.get('id')}"
            self.play_target(url, f"Playlist: {item.get('title')}")
        elif isinstance(item, tuple) and item[0] == "saved":
            _, name, url = item
            self.play_target(url, f"Saved: {name}")

    def _start_radio_selected(self):
        if not self.items or self.selected_idx >= len(self.items):
            return
        item = self.items[self.selected_idx]
        if not isinstance(item, Track):
            self.status_msg = "Radio is only available for individual tracks."
            return

        self.status_msg = f"Fetching radio recommendations for '{item.title}'..."
        track_id = item.id

        def worker():
            tracks = self.client.get_watch_playlist_tracks(track_id, limit=25)
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
        """Prompt user for a search query directly in the terminal."""
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

    def fetch_home_async(self):
        self.is_loading = True
        self.loading_text = "Loading Home & Recommendations..."
        self.items = []

        def worker():
            try:
                sections = self.client.get_home_sections(limit=8)
                self.home_sections = sections
                if self.current_tab == TAB_HOME:
                    self._rebuild_items_from_sections(sections)
                self.status_msg = f"Loaded {len(sections)} sections from YouTube Music."
            except Exception as e:
                self.status_msg = f"Failed to load home: {e}"
            finally:
                self.is_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def fetch_charts_async(self):
        self.is_loading = True
        self.loading_text = "Loading Charts and Trending..."
        self.items = []

        def worker():
            try:
                charts = self.client.get_charts()
                self.charts_sections = charts
                if self.current_tab == TAB_CHARTS:
                    self._rebuild_items_from_sections(charts)
                self.status_msg = f"Loaded charts and trending tracks."
            except Exception as e:
                self.status_msg = f"Failed to load charts: {e}"
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
                    self.fetch_home_async()
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
            {"label": "🌐 1. Open music.youtube.com in Browser", "action": "open_browser"},
            {"label": "⚡ 2. Auto-Detect & Extract Session (Zen, Firefox, Chrome, Brave...)", "action": "auto_login"},
            {"label": "🦊 3. Extract Session specifically from Zen Browser", "action": "zen_login"},
        ]
        if is_auth:
            self.items.append({"label": "🚪 4. Log Out (Remove Saved Credentials)", "action": "logout"})

    def _rebuild_items_from_sections(self, sections: List[Dict[str, Any]]):
        flattened: List[Any] = []
        for sec in sections:
            sec_title = sec.get("title", "Section")
            items = sec.get("items", [])
            if not items:
                continue
            flattened.append(f"--- 🎵 {sec_title.upper()} ---")
            for item in items[:10]:
                flattened.append(item)
        self.items = flattened

    def load_saved_playlists(self):
        self.saved_playlists = []
        if os.path.exists(PLAYLIST_FILE):
            try:
                with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "|" in line:
                            parts = line.split("|", 1)
                            self.saved_playlists.append((parts[0].strip(), parts[1].strip()))
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
        self.stdscr.addstr(0, len(header_left), "— YouTube Music TUI", curses.color_pair(6))

        if len(header_right) < max_x - 30:
            self.stdscr.addstr(0, max_x - len(header_right), header_right, auth_pair)
        self.stdscr.attroff(curses.A_BOLD)

        # 2. Tabs Row
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
            empty_msg = "No items to display. Press [Tab] to switch views or [/] to search."
            self.stdscr.addstr(content_top + 2, max(2, (max_x - len(empty_msg)) // 2), empty_msg, curses.color_pair(5))
        else:
            # Adjust scroll window
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
                    # Section Header
                    header_text = f" {item} "
                    self.stdscr.addstr(y, 1, header_text[:max_x - 2], curses.A_BOLD | curses.color_pair(1))
                elif isinstance(item, Track):
                    # Track Item
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
                    # Playlist Item
                    prefix = " ▶ 📁 " if is_selected else "   📁 "
                    title = item.get("title", "Playlist")
                    line_content = f"{prefix}{title} [Playlist]"
                    attr = curses.color_pair(2) | curses.A_BOLD if is_selected else curses.color_pair(4)
                    self.stdscr.addstr(y, 0, line_content[:max_x - 1], attr)

                elif isinstance(item, dict) and "label" in item:
                    # Login action item
                    prefix = " ▶ " if is_selected else "   "
                    line_content = f"{prefix}{item['label']}"
                    attr = curses.color_pair(2) | curses.A_BOLD if is_selected else curses.color_pair(6)
                    self.stdscr.addstr(y, 0, line_content[:max_x - 1], attr)

                elif isinstance(item, tuple) and item[0] == "saved":
                    # Saved Playlist item
                    prefix = " ▶ 📁 " if is_selected else "   📁 "
                    line_content = f"{prefix}{item[1]}"
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
        footer = " [Tab] View  [Enter] Play  [Space] Pause  [n/p] Skip  [/] Search  [r] Radio  [m] Mode  [q] Quit"
        self.stdscr.addstr(footer_y, 0, footer[:max_x - 1], curses.A_REVERSE | curses.color_pair(6))

        self.stdscr.refresh()


def main():
    curses.wrapper(lambda stdscr: TUIApp(stdscr).run())


if __name__ == "__main__":
    main()
