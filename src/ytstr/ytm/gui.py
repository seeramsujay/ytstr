"""
Lightweight YouTube Music GUI inspired by InnerTune and Metrolist.
Built with native Tkinter for ultra-low memory footprint (< 35 MB RAM).
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional

from ytstr.config import PLAYLIST_FILE, VERSION
from ytstr.core.types import Track
from ytstr.ytm.auth import AuthManager
from ytstr.ytm.client import YouTubeMusicClient

# Modern Obsidian / YouTube Music Palette
BG_DARK = "#0d0d0d"
BG_CARD = "#1a1a1a"
BG_CARD_HOVER = "#262626"
FG_WHITE = "#ffffff"
FG_MUTED = "#9e9e9e"
ACCENT_RED = "#ff0000"
ACCENT_BLUE = "#3ea6ff"
ACCENT_GREEN = "#2ba640"
BORDER_COLOR = "#2a2a2a"


class YTMDesktopApp:
    """Lightweight YouTube Music desktop browsing and login client."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"ytstr Music v{VERSION}")
        self.root.geometry("1000x720")
        self.root.configure(bg=BG_DARK)

        self.auth_mgr = AuthManager()
        self.client = YouTubeMusicClient(self.auth_mgr)

        self.current_tracks: List[Track] = []
        self.active_player_proc: Optional[subprocess.Popen] = None

        # Thread-safe UI dispatch queue (fixes Tkinter thread-safety on Linux)
        self._ui_queue: queue.Queue = queue.Queue()
        self._poll_ui_queue()

        self._setup_styles()
        self._build_header()
        self._build_content_area()
        self._build_bottom_player()

        # Load initial home sections asynchronously
        self.load_home()

    def _poll_ui_queue(self):
        """Periodically drain the UI queue from the main thread."""
        try:
            while not self._ui_queue.empty():
                callback, args, kwargs = self._ui_queue.get_nowait()
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    print(f"Error executing UI callback: {e}")
        except Exception:
            pass
        finally:
            self.root.after(50, self._poll_ui_queue)

    def _dispatch_to_ui(self, callback: Callable, *args, **kwargs):
        """Thread-safe submission of UI updates from background threads."""
        self._ui_queue.put((callback, args, kwargs))

    def _setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("default")
        self.style.configure(".", background=BG_DARK, foreground=FG_WHITE, font=("Sans", 10))
        self.style.configure("TFrame", background=BG_DARK)
        self.style.configure("Card.TFrame", background=BG_CARD)
        self.style.configure(
            "TButton",
            background=BG_CARD,
            foreground=FG_WHITE,
            borderwidth=0,
            padding=6,
            font=("Sans", 9, "bold"),
        )
        self.style.map(
            "TButton",
            background=[("active", BG_CARD_HOVER), ("pressed", ACCENT_RED)],
            foreground=[("active", FG_WHITE)],
        )
        self.style.configure("TCombobox", fieldbackground=BG_CARD, background=BG_CARD, foreground=FG_WHITE)

    def _build_header(self):
        header = tk.Frame(self.root, bg=BG_DARK, padx=16, pady=12)
        header.pack(fill=tk.X)

        # Brand
        title_box = tk.Frame(header, bg=BG_DARK)
        title_box.pack(side=tk.LEFT, padx=(0, 20))
        tk.Label(title_box, text="ytstr", font=("Sans", 16, "bold"), fg=ACCENT_RED, bg=BG_DARK).pack(side=tk.LEFT)
        tk.Label(title_box, text=" MUSIC", font=("Sans", 11, "bold"), fg=FG_WHITE, bg=BG_DARK).pack(side=tk.LEFT)

        # Nav Buttons
        nav_frame = tk.Frame(header, bg=BG_DARK)
        nav_frame.pack(side=tk.LEFT, padx=10)

        tk.Button(
            nav_frame, text="Home", command=self.load_home, bg=BG_CARD, fg=FG_WHITE,
            activebackground=BG_CARD_HOVER, activeforeground=FG_WHITE, relief=tk.FLAT, padx=10, pady=4
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            nav_frame, text="Charts & Trending", command=self.load_charts, bg=BG_CARD, fg=FG_WHITE,
            activebackground=BG_CARD_HOVER, activeforeground=FG_WHITE, relief=tk.FLAT, padx=10, pady=4
        ).pack(side=tk.LEFT, padx=4)

        # Search Bar
        search_frame = tk.Frame(header, bg=BG_DARK)
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=15)

        self.search_entry = tk.Entry(
            search_frame, bg=BG_CARD, fg=FG_WHITE, insertbackground=FG_WHITE,
            font=("Sans", 10), relief=tk.FLAT, bd=6
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<Return>", lambda e: self.do_search())

        tk.Button(
            search_frame, text="🔍 Search", command=self.do_search, bg=BG_CARD_HOVER, fg=FG_WHITE,
            activebackground=ACCENT_RED, relief=tk.FLAT, padx=10, pady=4
        ).pack(side=tk.LEFT, padx=(4, 0))

        # Mode Selector
        mode_frame = tk.Frame(header, bg=BG_DARK)
        mode_frame.pack(side=tk.LEFT, padx=10)
        tk.Label(mode_frame, text="Mode:", fg=FG_MUTED, bg=BG_DARK, font=("Sans", 8)).pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="Direct Low-RAM (--no-mix)")
        mode_menu = ttk.Combobox(
            mode_frame, textvariable=self.mode_var, width=22, state="readonly",
            values=[
                "Direct Low-RAM (--no-mix)",
                "Auto-DJ (Spectral)",
                "Light Mix (Crossfade)",
                "Direct Stream (--stream)",
            ]
        )
        mode_menu.pack(side=tk.LEFT, padx=4)

        # Save File-by-file Toggle
        self.save_var = tk.BooleanVar(value=False)
        save_check = tk.Checkbutton(
            header, text="Save Files", variable=self.save_var, bg=BG_DARK, fg=FG_WHITE,
            selectcolor=BG_CARD, activebackground=BG_DARK, activeforeground=FG_WHITE
        )
        save_check.pack(side=tk.LEFT, padx=8)

        # Login / Account Button
        self.auth_btn = tk.Button(
            header, text="Log In" if not self.auth_mgr.is_authenticated() else "Account ✓",
            command=self.open_login_modal,
            bg=ACCENT_RED if not self.auth_mgr.is_authenticated() else ACCENT_GREEN,
            fg=FG_WHITE, relief=tk.FLAT, font=("Sans", 9, "bold"), padx=12, pady=4
        )
        self.auth_btn.pack(side=tk.RIGHT)

    def _build_content_area(self):
        self.canvas_frame = tk.Frame(self.root, bg=BG_DARK)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        self.canvas = tk.Canvas(self.canvas_frame, bg=BG_DARK, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)

        self.scroll_content = tk.Frame(self.canvas, bg=BG_DARK)
        self.scroll_content.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width)
        )

        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_bottom_player(self):
        player_bar = tk.Frame(self.root, bg=BG_CARD, padx=16, pady=8, bd=1, relief=tk.SOLID)
        player_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_label = tk.Label(
            player_bar, text="Ready. Select a track or playlist to stream.",
            bg=BG_CARD, fg=FG_MUTED, font=("Sans", 9)
        )
        self.status_label.pack(side=tk.LEFT)

        controls = tk.Frame(player_bar, bg=BG_CARD)
        controls.pack(side=tk.RIGHT)

        tk.Button(
            controls, text="⏹ Stop Player", command=self.stop_playback,
            bg="#333333", fg=FG_WHITE, relief=tk.FLAT, padx=10, pady=2
        ).pack(side=tk.RIGHT, padx=4)

    def _clear_content(self):
        for widget in self.scroll_content.winfo_children():
            widget.destroy()

    def _show_loading(self, message: str = "Loading YouTube Music..."):
        self._clear_content()
        lbl = tk.Label(
            self.scroll_content, text=f"⏳ {message}",
            font=("Sans", 13), fg=FG_MUTED, bg=BG_DARK, pady=50
        )
        lbl.pack(fill=tk.X)

    def _show_error(self, message: str, retry_func=None):
        self._clear_content()
        err_box = tk.Frame(self.scroll_content, bg=BG_DARK, pady=40)
        err_box.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            err_box, text="⚠️ Unable to Load Content",
            font=("Sans", 14, "bold"), fg=ACCENT_RED, bg=BG_DARK
        ).pack(pady=(0, 8))

        tk.Label(
            err_box, text=message,
            font=("Sans", 10), fg=FG_MUTED, bg=BG_DARK, wraplength=600
        ).pack(pady=(0, 16))

        if retry_func:
            tk.Button(
                err_box, text="🔄 Retry", command=retry_func,
                bg=BG_CARD, fg=FG_WHITE, relief=tk.FLAT, padx=14, pady=6, font=("Sans", 9, "bold")
            ).pack()

    def load_home(self):
        self._show_loading("Loading YouTube Music Home (Listen Again, Quick Picks)...")

        def worker():
            try:
                sections = self.client.get_home_sections(limit=6)
                self._dispatch_to_ui(self._render_sections, sections, "Home & Recommendations")
            except Exception as e:
                self._dispatch_to_ui(self._show_error, f"Failed to load home: {e}", self.load_home)

        threading.Thread(target=worker, daemon=True).start()

    def load_charts(self):
        self._show_loading("Loading Charts and Trending...")

        def worker():
            try:
                charts = self.client.get_charts()
                self._dispatch_to_ui(self._render_sections, charts, "Charts & Trending")
            except Exception as e:
                self._dispatch_to_ui(self._show_error, f"Failed to load charts: {e}", self.load_charts)

        threading.Thread(target=worker, daemon=True).start()

    def do_search(self):
        query = self.search_entry.get().strip()
        if not query:
            return

        self._show_loading(f"Searching for '{query}'...")

        def worker():
            try:
                tracks = self.client.search_tracks(query, limit=25)
                self._dispatch_to_ui(self._render_track_list, tracks, f"Search Results for '{query}'")
            except Exception as e:
                self._dispatch_to_ui(self._show_error, f"Search error: {e}", self.do_search)

        threading.Thread(target=worker, daemon=True).start()

    def _render_sections(self, sections: List[Dict[str, Any]], title: str):
        self._clear_content()

        header_lbl = tk.Label(
            self.scroll_content, text=title,
            font=("Sans", 14, "bold"), fg=FG_WHITE, bg=BG_DARK, pady=10
        )
        header_lbl.pack(anchor="w")

        if not sections:
            tk.Label(
                self.scroll_content, text="No items found. Check internet connection or log in.",
                fg=FG_MUTED, bg=BG_DARK, pady=20
            ).pack(anchor="w")
            return

        for section in sections:
            sec_title = section.get("title", "Section")
            items = section.get("items", [])
            if not items:
                continue

            sec_frame = tk.Frame(self.scroll_content, bg=BG_DARK, pady=8)
            sec_frame.pack(fill=tk.X)

            tk.Label(
                sec_frame, text=sec_title,
                font=("Sans", 12, "bold"), fg=ACCENT_RED, bg=BG_DARK
            ).pack(anchor="w", pady=(0, 6))

            for item in items[:8]:
                try:
                    if isinstance(item, Track):
                        self._render_track_row(sec_frame, item)
                    elif isinstance(item, dict):
                        self._render_playlist_row(sec_frame, item)
                except Exception:
                    continue

        # Force geometry recalculation so scrolling works immediately
        self.scroll_content.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _render_track_list(self, tracks: List[Track], title: str):
        self._clear_content()

        header_lbl = tk.Label(
            self.scroll_content, text=title,
            font=("Sans", 14, "bold"), fg=FG_WHITE, bg=BG_DARK, pady=10
        )
        header_lbl.pack(anchor="w")

        if not tracks:
            tk.Label(
                self.scroll_content, text="No tracks matched the query.",
                fg=FG_MUTED, bg=BG_DARK, pady=20
            ).pack(anchor="w")
            return

        for track in tracks:
            try:
                self._render_track_row(self.scroll_content, track)
            except Exception:
                continue

        self.scroll_content.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _render_track_row(self, parent: tk.Widget, track: Track):
        row = tk.Frame(parent, bg=BG_CARD, padx=12, pady=8, bd=1, relief=tk.SOLID)
        row.pack(fill=tk.X, pady=3)

        info_box = tk.Frame(row, bg=BG_CARD)
        info_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(
            info_box, text=track.title,
            font=("Sans", 10, "bold"), fg=FG_WHITE, bg=BG_CARD, anchor="w"
        ).pack(fill=tk.X)

        sub_text = track.artist or "YouTube Music"
        if track.duration_sec > 0:
            m = int(track.duration_sec // 60)
            s = int(track.duration_sec % 60)
            sub_text += f" • {m}:{s:02d}"

        tk.Label(
            info_box, text=sub_text,
            font=("Sans", 8), fg=FG_MUTED, bg=BG_CARD, anchor="w"
        ).pack(fill=tk.X)

        btn_box = tk.Frame(row, bg=BG_CARD)
        btn_box.pack(side=tk.RIGHT)

        tk.Button(
            btn_box, text="▶ Play", command=lambda t=track: self.play_track(t),
            bg=ACCENT_RED, fg=FG_WHITE, relief=tk.FLAT, font=("Sans", 8, "bold"), padx=8, pady=2
        ).pack(side=tk.LEFT, padx=3)

        tk.Button(
            btn_box, text="📻 Radio", command=lambda t=track: self.start_radio(t),
            bg="#333333", fg=FG_WHITE, relief=tk.FLAT, font=("Sans", 8), padx=8, pady=2
        ).pack(side=tk.LEFT, padx=3)

        tk.Button(
            btn_box, text="➕ Save", command=lambda t=track: self.add_to_saved_playlists(t),
            bg="#333333", fg=FG_WHITE, relief=tk.FLAT, font=("Sans", 8), padx=8, pady=2
        ).pack(side=tk.LEFT, padx=3)

    def _render_playlist_row(self, parent: tk.Widget, pl_dict: dict):
        row = tk.Frame(parent, bg=BG_CARD, padx=12, pady=8, bd=1, relief=tk.SOLID)
        row.pack(fill=tk.X, pady=3)

        info_box = tk.Frame(row, bg=BG_CARD)
        info_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        title = pl_dict.get("title", "Playlist")
        tk.Label(
            info_box, text=f"📁 {title}",
            font=("Sans", 10, "bold"), fg=ACCENT_BLUE, bg=BG_CARD, anchor="w"
        ).pack(fill=tk.X)

        btn_box = tk.Frame(row, bg=BG_CARD)
        btn_box.pack(side=tk.RIGHT)

        pl_id = pl_dict.get("id")
        tk.Button(
            btn_box, text="▶ Play Playlist", command=lambda pid=pl_id, name=title: self.play_playlist(pid, name),
            bg=ACCENT_BLUE, fg=FG_WHITE, relief=tk.FLAT, font=("Sans", 8, "bold"), padx=8, pady=2
        ).pack(side=tk.LEFT, padx=3)

    def play_track(self, track: Track):
        self._launch_ytstr_engine(target=track.web_url, label=track.display_title())

    def play_playlist(self, playlist_id: str, name: str):
        url = f"https://www.youtube.com/playlist?list={playlist_id}"
        self._launch_ytstr_engine(target=url, label=f"Playlist: {name}")

    def start_radio(self, track: Track):
        self.status_label.config(text=f"Fetching radio for {track.title}...")

        def worker():
            try:
                tracks = self.client.get_watch_playlist_tracks(track.id, limit=25)
                if tracks:
                    def on_success():
                        self._render_track_list(tracks, f"Radio: {track.display_title()}")
                        self._launch_ytstr_engine(track.web_url, f"Radio: {track.title}")
                    self._dispatch_to_ui(on_success)
                else:
                    self._dispatch_to_ui(lambda: messagebox.showwarning("Radio", "Could not fetch radio tracks."))
            except Exception as e:
                self._dispatch_to_ui(lambda err=str(e): messagebox.showerror("Radio Error", f"Radio failed: {err}"))

        threading.Thread(target=worker, daemon=True).start()

    def add_to_saved_playlists(self, track: Track):
        try:
            with open(PLAYLIST_FILE, "a", encoding="utf-8") as f:
                f.write(f"{track.display_title()}|{track.web_url}\n")
            messagebox.showinfo("Saved", f"Added '{track.display_title()}' to saved playlists!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def _launch_ytstr_engine(self, target: str, label: str):
        self.stop_playback()

        mode_choice = self.mode_var.get()
        cmd = [sys.executable, "-m", "ytstr", target]

        if "No-Mix" in mode_choice:
            cmd.append("--no-mix")
        elif "Light Mix" in mode_choice:
            cmd.append("--light-mix")
        elif "Direct Stream" in mode_choice:
            cmd.append("--stream")

        if self.save_var.get():
            save_path = os.path.expanduser("~/Music/ytstr")
            os.makedirs(save_path, exist_ok=True)
            cmd.extend(["--save", save_path])

        self.status_label.config(text=f"▶ Streaming: {label} [{mode_choice}]")

        try:
            self.active_player_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            messagebox.showerror("Player Error", f"Could not launch ytstr player:\n{e}")

    def stop_playback(self):
        if self.active_player_proc:
            try:
                self.active_player_proc.terminate()
            except Exception:
                pass
            self.active_player_proc = None
        self.status_label.config(text="Player stopped.")

    def open_login_modal(self):
        """Modal window for YouTube Music Login (Auto Browser Extraction & Browser Launch)."""
        modal = tk.Toplevel(self.root)
        modal.title("YouTube Music Login")
        modal.geometry("620x560")
        modal.configure(bg=BG_DARK)
        modal.transient(self.root)
        modal.grab_set()

        tk.Label(
            modal, text="YouTube Music Authentication",
            font=("Sans", 14, "bold"), fg=ACCENT_RED, bg=BG_DARK
        ).pack(pady=(16, 6))

        status_txt = "Logged In ✓" if self.auth_mgr.is_authenticated() else "Not Logged In"
        status_color = ACCENT_GREEN if self.auth_mgr.is_authenticated() else FG_MUTED

        status_lbl = tk.Label(
            modal, text=f"Account Status: {status_txt}",
            font=("Sans", 10, "bold"), fg=status_color, bg=BG_DARK
        )
        status_lbl.pack(pady=(0, 12))

        # Card 1: 1-Click Browser Login (Sonora / Modern Style)
        auto_card = tk.LabelFrame(
            modal, text=" ⚡ 1-Click Browser Login (Recommended) ",
            bg=BG_CARD, fg=FG_WHITE, font=("Sans", 10, "bold"), padx=14, pady=12, relief=tk.GROOVE
        )
        auto_card.pack(fill=tk.X, padx=16, pady=8)

        tk.Label(
            auto_card,
            text="Step 1: Open YouTube Music in your browser and sign in.",
            font=("Sans", 9), fg=FG_WHITE, bg=BG_CARD
        ).pack(anchor="w", pady=(0, 6))

        tk.Button(
            auto_card, text="🌐 Open music.youtube.com in Browser",
            command=self.auth_mgr.open_browser_for_login,
            bg="#222222", fg=ACCENT_BLUE, relief=tk.FLAT, font=("Sans", 9, "bold"), padx=10, pady=4
        ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            auto_card,
            text="Step 2: Automatically import the active session:",
            font=("Sans", 9), fg=FG_WHITE, bg=BG_CARD
        ).pack(anchor="w", pady=(4, 6))

        import_row = tk.Frame(auto_card, bg=BG_CARD)
        import_row.pack(fill=tk.X, pady=(0, 4))

        tk.Label(import_row, text="Browser:", fg=FG_MUTED, bg=BG_CARD, font=("Sans", 9)).pack(side=tk.LEFT, padx=(0, 6))

        browser_var = tk.StringVar(value="auto")
        browser_combo = ttk.Combobox(
            import_row, textvariable=browser_var, width=18, state="readonly",
            values=["auto", "zen", "firefox", "chrome", "brave", "edge", "chromium", "opera", "vivaldi"]
        )
        browser_combo.pack(side=tk.LEFT, padx=(0, 10))

        import_status_lbl = tk.Label(auto_card, text="", fg=FG_MUTED, bg=BG_CARD, font=("Sans", 8))

        def do_auto_import():
            chosen_browser = browser_var.get()
            import_status_lbl.config(text=f"Importing session from {chosen_browser}...", fg=ACCENT_BLUE)
            auto_card.update()

            def worker():
                success, msg = self.auth_mgr.import_cookies_from_browser(chosen_browser)
                def on_done():
                    if success:
                        messagebox.showinfo("Success", f"{msg}\nAccount active!", parent=modal)
                        self.client._init_ytm()
                        self.auth_btn.config(text="Account ✓", bg=ACCENT_GREEN)
                        status_lbl.config(text="Account Status: Logged In ✓", fg=ACCENT_GREEN)
                        modal.destroy()
                        self.load_home()
                    else:
                        import_status_lbl.config(text=msg, fg=ACCENT_RED)
                        messagebox.showwarning("Login Incomplete", msg, parent=modal)

                self._dispatch_to_ui(on_done)

            threading.Thread(target=worker, daemon=True).start()

        tk.Button(
            import_row, text="⚡ Import Session & Log In", command=do_auto_import,
            bg=ACCENT_RED, fg=FG_WHITE, relief=tk.FLAT, font=("Sans", 9, "bold"), padx=12, pady=4
        ).pack(side=tk.LEFT)

        import_status_lbl.pack(anchor="w", pady=(4, 0))

        # Card 2: Manual Headers Fallback
        manual_card = tk.LabelFrame(
            modal, text=" 📝 Manual Headers Fallback ",
            bg=BG_CARD, fg=FG_MUTED, font=("Sans", 9, "bold"), padx=14, pady=8, relief=tk.GROOVE
        )
        manual_card.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        tk.Label(
            manual_card,
            text="Optional: Paste raw request headers from DevTools (F12 -> Network):",
            font=("Sans", 8), fg=FG_MUTED, bg=BG_CARD
        ).pack(anchor="w", pady=(0, 4))

        headers_text = tk.Text(
            manual_card, height=4, bg="#111111", fg=FG_WHITE, insertbackground=FG_WHITE,
            relief=tk.FLAT, bd=4, font=("Monospace", 8)
        )
        headers_text.pack(fill=tk.BOTH, expand=True, pady=4)

        manual_btn_row = tk.Frame(manual_card, bg=BG_CARD)
        manual_btn_row.pack(fill=tk.X, pady=(4, 0))

        def save_manual_headers():
            content = headers_text.get("1.0", tk.END).strip()
            if not content:
                messagebox.showwarning("Empty", "Please paste headers.", parent=modal)
                return
            if self.auth_mgr.save_headers(content):
                messagebox.showinfo("Success", "Authenticated via headers!", parent=modal)
                self.client._init_ytm()
                self.auth_btn.config(text="Account ✓", bg=ACCENT_GREEN)
                modal.destroy()
                self.load_home()
            else:
                messagebox.showerror("Error", "Could not parse headers.", parent=modal)

        def do_logout():
            self.auth_mgr.logout()
            self.client._init_ytm()
            self.auth_btn.config(text="Log In", bg=ACCENT_RED)
            messagebox.showinfo("Logged Out", "Authentication cleared.", parent=modal)
            modal.destroy()
            self.load_home()

        tk.Button(
            manual_btn_row, text="💾 Save Pasted Headers", command=save_manual_headers,
            bg="#333333", fg=FG_WHITE, relief=tk.FLAT, font=("Sans", 8), padx=8, pady=3
        ).pack(side=tk.LEFT)

        if self.auth_mgr.is_authenticated():
            tk.Button(
                manual_btn_row, text="🚪 Log Out", command=do_logout,
                bg="#551111", fg=FG_WHITE, relief=tk.FLAT, font=("Sans", 8), padx=8, pady=3
            ).pack(side=tk.RIGHT)


def main():
    root = tk.Tk()
    app = YTMDesktopApp(root)

    def on_closing():
        app.stop_playback()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
