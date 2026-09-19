"""
Unit tests for ytstr Terminal User Interface (TUI).
"""
import curses
from unittest.mock import MagicMock, patch

from ytstr.core.types import Track
from ytstr.ui.tui import (
    TAB_LIKED,
    TAB_LOGIN,
    TAB_PLAYLISTS,
    TAB_QUEUE,
    TAB_RECOMMENDED,
    TAB_SEARCH,
    TUIApp,
)


def make_mock_stdscr():
    stdscr = MagicMock()
    stdscr.getmaxyx.return_value = (30, 100)
    stdscr.getch.return_value = -1
    return stdscr


def test_tui_initialization():
    stdscr = make_mock_stdscr()
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=True), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"):
        app = TUIApp(stdscr)

        assert app.current_tab == TAB_RECOMMENDED
        assert app.mode_idx == 0
        assert app.selected_idx == 0
        assert app.now_playing is None


def test_tui_navigation_and_modes():
    stdscr = make_mock_stdscr()
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=True), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"), \
         patch.object(TUIApp, "fetch_playlists_async"), \
         patch.object(TUIApp, "fetch_liked_async"):
        app = TUIApp(stdscr)

        # Tab switching
        app._handle_input(ord('2'))
        assert app.current_tab == TAB_PLAYLISTS

        app._handle_input(ord('3'))
        assert app.current_tab == TAB_LIKED

        app._handle_input(ord('4'))
        assert app.current_tab == TAB_QUEUE

        app._handle_input(ord('6'))
        assert app.current_tab == TAB_LOGIN
        assert len(app.items) >= 3

        # Cycle playback mode
        prev_mode = app.mode_idx
        app._handle_input(ord('m'))
        assert app.mode_idx == (prev_mode + 1) % 4

        # Moving selection in list
        app.items = [
            Track(id="1", title="Song 1", artist="Artist 1", duration_sec=180, url="http://1"),
            Track(id="2", title="Song 2", artist="Artist 2", duration_sec=200, url="http://2"),
        ]
        app.selected_idx = 0
        app._handle_input(ord('j'))  # Down
        assert app.selected_idx == 1
        app._handle_input(ord('k'))  # Up
        assert app.selected_idx == 0


def test_tui_draw_no_crash():
    stdscr = make_mock_stdscr()
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=True), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"):
        app = TUIApp(stdscr)
        app.items = [
            Track(id="test1", title="Bohemian Rhapsody", artist="Queen", duration_sec=354, url="http://test"),
            {"type": "playlist", "id": "pl1", "title": "Rock Classics", "count": 25},
        ]
        app._draw()
        assert stdscr.erase.called
        assert stdscr.refresh.called


def test_tui_remove_from_queue():
    stdscr = make_mock_stdscr()
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=True), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"):
        app = TUIApp(stdscr)
        t1 = Track(id="1", title="Track 1")
        t2 = Track(id="2", title="Track 2")
        t3 = Track(id="3", title="Track 3")
        app.queue_tracks = [t1, t2, t3]
        app.current_queue_idx = 0
        app.current_tab = TAB_QUEUE
        app.items = list(app.queue_tracks)
        app.selected_idx = 1  # Selected Track 2 (upcoming)

        # Press 'd' to remove Track 2
        app._handle_input(ord('d'))
        assert len(app.queue_tracks) == 2
        assert app.queue_tracks[1].id == "3"


def test_tui_auto_dj_handoff():
    stdscr = make_mock_stdscr()
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=True), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"):
        app = TUIApp(stdscr)
        app.ipc = MagicMock()

        t1 = Track(id="1", title="Track 1", duration_sec=180.0)
        t2 = Track(id="2", title="Track 2", duration_sec=200.0)
        app.now_playing = t1.display_title()
        app.queue_tracks = [t1, t2]
        app.current_queue_idx = 0
        app.duration = 180.0
        app.time_pos = 100.0
        app.mode_idx = 0  # Direct Low-RAM

        # Cycle mode to 1 (Light Mix) -> should trigger pending_dj_handoff
        app._handle_input(ord('m'))
        assert app.mode_idx == 1
        assert app.pending_dj_handoff is True
        assert "DJ engine warming up" in app.status_msg

        # Mock playback nearing end (remaining <= 4.0s)
        app.time_pos = 177.0
        with patch.object(app, "play_track_and_start_radio") as mock_play:
            with patch("os.path.exists", return_value=True):
                app._update_playback_status()
                assert app.pending_dj_handoff is False
                assert mock_play.called
                args, kwargs = mock_play.call_args
                assert args[0].id == "2"
