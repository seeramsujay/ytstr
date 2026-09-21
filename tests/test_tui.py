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


def test_tui_radio_queue_jump_retains_history():
    """Verify jumping forward in queue keeps earlier tracks for rewind and avoids queue wiping."""
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

        tracks = [
            Track(id=f"track_{i}", title=f"Track {i}", artist="Artist", duration_sec=180.0)
            for i in range(5)
        ]
        app.queue_tracks = list(tracks)
        app.current_queue_idx = 0
        app.current_tab = TAB_QUEUE
        app.items = list(tracks)

        # User selects track 3 in radio queue and presses Enter
        app.selected_idx = 3
        with patch.object(app, "_play_direct_track_at_index") as mock_play:
            app._handle_input(10)  # Enter key
            assert mock_play.called
            mock_play.assert_called_once_with(3)

        assert app.current_queue_idx == 3
        assert app.now_playing == tracks[3].display_title()
        # Entire queue history must be preserved (0, 1, 2, 3, 4)
        assert len(app.queue_tracks) == 5
        assert app.queue_tracks[0].id == "track_0"
        assert app.queue_tracks[4].id == "track_4"


def test_tui_rewind_and_prev():
    """Verify rewind in radio queue: restarts if > 3s, steps back to previous track if <= 3s."""
    stdscr = make_mock_stdscr()
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=True), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"):
        app = TUIApp(stdscr)
        mock_ipc = MagicMock()
        app.ipc = mock_ipc

        tracks = [
            Track(id="t0", title="First Song", duration_sec=200.0),
            Track(id="t1", title="Second Song", duration_sec=200.0),
            Track(id="t2", title="Third Song", duration_sec=200.0),
        ]
        app.queue_tracks = list(tracks)
        app.current_queue_idx = 1
        app.now_playing = tracks[1].display_title()

        # Case 1: time_pos > 3.0s -> should seek to beginning of current track
        app.time_pos = 15.0
        app._skip_prev()
        mock_ipc.seek.assert_called_with(0.0, "absolute")
        assert app.current_queue_idx == 1  # Stays on track 1

        # Case 2: time_pos <= 3.0s -> should step back to previous track in queue
        app.time_pos = 1.5
        with patch.object(app, "_play_direct_track_at_index") as mock_play:
            app._skip_prev()
            assert app.current_queue_idx == 0
            assert app.now_playing == tracks[0].display_title()
            mock_play.assert_called_once_with(0)


def test_tui_playback_modes_and_live_switching():
    """Verify cycling modes, direct stream zero-cache routing, and active_ipc behavior."""
    stdscr = make_mock_stdscr()
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=True), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"):
        app = TUIApp(stdscr)
        mock_ipc = MagicMock()
        app.ipc = mock_ipc

        t0 = Track(id="track0", title="Track 0", duration_sec=180.0)
        t1 = Track(id="track1", title="Track 1", duration_sec=200.0)
        app.queue_tracks = [t0, t1]
        app.current_queue_idx = 0
        app.now_playing = t0.display_title()
        app.duration = 180.0
        app.time_pos = 20.0

        # Mode 0 (Direct Low-RAM) -> seek & volume use direct IPC
        app._seek(5.0)
        mock_ipc.seek.assert_called_with(5.0, "relative")
        app._adjust_volume(5.0)
        mock_ipc.adjust_volume.assert_called_with(5.0)

        # Mode switch to Mode 1 (Light Mix) -> sets pending handoff
        app._handle_mode_switch()
        assert app.mode_idx == 1
        assert app.pending_dj_handoff is True

        # Mode switch to Mode 2 (Direct Stream) -> pending handoff cleared
        app._handle_mode_switch()
        assert app.mode_idx == 2
        assert app.pending_dj_handoff is False

        # In Mode 2 (Direct Stream), play track must fetch direct URL with no disk caching
        with patch.object(app.downloader, "get_direct_stream_url", return_value="https://googlevideo.com/stream"):
            app._play_direct_track_at_index(1)
            mock_ipc.load_file.assert_called_with("https://googlevideo.com/stream", mode="replace")

        # Mode switch to Mode 3 (Auto-DJ Spectral)
        app._handle_mode_switch()
        assert app.mode_idx == 3
        assert app.pending_dj_handoff is True

        # Mode switch back to Mode 0 (Direct Low-RAM)
        app._handle_mode_switch()
        assert app.mode_idx == 0
        assert app.pending_dj_handoff is False


def test_tui_rebuild_items_from_sections():
    """Verify sections with 'items' or 'contents' parse properly and don't throw KeyError."""
    stdscr = make_mock_stdscr()
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=True), \
         patch("curses.init_pair"), \
         patch("curses.color_pair", return_value=0), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"):
        app = TUIApp(stdscr)

        t1 = Track(id="track1", title="Track 1", duration_sec=180.0)
        t2 = Track(id="track2", title="Track 2", duration_sec=210.0)

        # Mix of "items" (YTMusicClient style) and "contents" (raw YTM style)
        sections = [
            {"title": "Listen Again", "items": [t1]},
            {"title": "Mixed For You", "contents": [t2]},
            {"title": "Empty Section", "items": []},
            "invalid_section",
        ]

        app._rebuild_items_from_sections(sections)

        # Verify headers and tracks
        assert len(app.items) == 4
        assert app.items[0] == {"type": "section_header", "title": "Listen Again"}
        assert app.items[1] == t1
        assert app.items[2] == {"type": "section_header", "title": "Mixed For You"}
        assert app.items[3] == t2
        assert app.selected_idx == 1  # Should default to first playable track!

        # Activating section header should step into first track
        app.selected_idx = 0
        with patch.object(app, "play_track_and_start_radio") as mock_play:
            app._activate_selected()
            mock_play.assert_called_once_with(t1)
