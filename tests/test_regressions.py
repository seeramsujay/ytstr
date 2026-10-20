"""
Regression tests for previously broken behaviour across CLI, cache, DJ engine and TUI.
"""
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydub import AudioSegment

from ytstr.core.player import YtstrCoordinator
from ytstr.core.types import Track
from ytstr.downloader.cache import CacheManager
from ytstr.playback.dj_player import DJPlayer
from ytstr.ui.tui import TAB_PLAYLISTS, TUIApp
from ytstr.ytm.client import YouTubeMusicClient


def make_app():
    stdscr = MagicMock()
    stdscr.getmaxyx.return_value = (30, 100)
    stdscr.getch.return_value = -1
    with patch("curses.curs_set"), \
         patch("curses.use_default_colors"), \
         patch("curses.has_colors", return_value=False), \
         patch.object(TUIApp, "_ensure_mpv"), \
         patch.object(TUIApp, "fetch_recommended_async"):
        return TUIApp(stdscr)


def test_cli_coordinator_constructs_cache_manager():
    with patch("signal.signal"):
        coord = YtstrCoordinator(target="lofi")
    assert coord.cache_mgr.session_id.startswith("cli_")


def test_cli_coordinator_returns_exit_code_when_no_tracks():
    with patch("signal.signal"):
        coord = YtstrCoordinator(target="lofi")
    assert coord.run() == 1


def test_client_search_accepts_filter_type():
    client = YouTubeMusicClient()
    client._ytm = MagicMock()
    client._ytm.search.return_value = [{"videoId": "abcdefghijk", "title": "Song"}]
    tracks = client.search("query", filter_type="songs", limit=5)
    assert [t.id for t in tracks] == ["abcdefghijk"]
    client._ytm.search.assert_called_with("query", filter="songs", limit=5)


def test_cache_marks_track_unavailable_after_repeated_failures():
    mgr = CacheManager(session_id="regress")
    track = Track(id="broken", title="Broken")
    downloader = MagicMock()
    downloader.download_track.return_value = False

    assert mgr.download_if_needed(track, downloader) is True
    assert not mgr.is_unavailable(track)
    assert mgr.download_if_needed(track, downloader) is True
    assert mgr.is_unavailable(track)
    # Unavailable tracks are no longer retried
    assert mgr.download_if_needed(track, downloader) is False
    assert downloader.download_track.call_count == 2
    mgr.cleanup()


def test_dj_next_track_resumes_after_crossfade_overlap(tmp_path):
    """The incoming track must continue after the overlap, not replay its head."""
    t0 = Track(id="t0", title="Zero")
    t1 = Track(id="t1", title="One")
    cache_mgr = MagicMock()
    for t in (t0, t1):
        (tmp_path / f"{t.id}.opus").write_bytes(b"0" * 2048)
    cache_mgr.find_cached_file.side_effect = lambda t: tmp_path / f"{t.id}.opus"
    cache_mgr.track_is_cached.return_value = True
    cache_mgr.is_unavailable.return_value = False

    player = DJPlayer([t0, t1], cache_mgr, MagicMock(), light_mix=True, crossfade_sec=3.0)
    player._download_worker = lambda: None
    player._launch_mpv = lambda: None
    player._write_pcm_to_mpv = lambda raw: True

    reads = []

    def fake_chunk(path, start_s, dur_s):
        reads.append((Path(path).stem, round(start_s, 3)))
        if reads[-1][0] == "t1" and start_s > 0.0:
            player._quit_flag = True  # First body read of the incoming track
        return AudioSegment.silent(duration=int(dur_s * 1000))

    with patch("ytstr.playback.dj_player.get_audio_duration", return_value=10.0), \
         patch("ytstr.playback.dj_player.get_audio_chunk", side_effect=fake_chunk), \
         patch("ytstr.playback.dj_player.apply_transition",
               return_value=(AudioSegment.silent(duration=3000), 3000)):
        worker = threading.Thread(target=player._stream_worker, daemon=True)
        worker.start()
        worker.join(timeout=5.0)

    assert not worker.is_alive()
    t1_reads = [start for name, start in reads if name == "t1"]
    # First read of t1 is the transition head (0.0); streaming then resumes at 3.0s
    body_reads = [s for s in t1_reads if s > 0.0]
    assert body_reads and body_reads[0] == 3.0


def test_dj_jump_works_after_queue_end():
    player = DJPlayer([Track(id="a", title="A")], MagicMock(), MagicMock())
    player._launch_mpv = lambda: None
    player._download_worker = lambda: None
    player.cache_mgr.find_cached_file.return_value = None
    player.cache_mgr.is_unavailable.return_value = True  # Only track is unplayable

    worker = threading.Thread(target=player._stream_worker, daemon=True)
    worker.start()
    time.sleep(0.3)  # Worker skips the unavailable track and idles at queue end
    player.jump_to(0)
    time.sleep(0.3)
    player._quit_flag = True
    worker.join(timeout=2.0)
    assert player.jump_to_idx is None  # Jump was consumed despite being at the end


def test_tui_direct_mode_advances_when_idle_after_eof():
    app = make_app()
    app.queue_tracks = [Track(id="a", title="A"), Track(id="b", title="B")]
    app.current_queue_idx = 0
    app.active_engine = "direct"
    app._direct_started = True  # Track had been playing

    ipc = MagicMock()
    # Idle after EOF: playback-time is unavailable so the default is returned
    ipc.get_float_property.side_effect = lambda prop, default=0.0: default
    ipc.get_bool_property.side_effect = lambda prop, default=False: prop == "idle-active"
    app.ipc = ipc

    with patch("os.path.exists", return_value=True), \
         patch.object(app, "_play_direct_track_at_index") as mock_play:
        app._update_playback_status()
    mock_play.assert_called_once_with(1)
    app._quit_flag = True


def test_tui_shift_p_plays_playlist_and_p_goes_back():
    app = make_app()
    with patch.object(app, "_play_playlist_direct") as mock_pl, \
         patch.object(app, "_skip_prev") as mock_prev:
        app._handle_input(ord("P"))
        app._handle_input(ord("p"))
    mock_pl.assert_called_once()
    mock_prev.assert_called_once()
    app._quit_flag = True


def test_tui_save_uses_path_and_sanitized_filename():
    app = make_app()
    app.items = [Track(id="x", title="AC/DC: Back?", artist="Band")]
    app.selected_idx = 0
    saved = {}

    def fake_download(track, dest):
        saved["dest"] = dest
        return True

    with patch.object(app.downloader, "download_track", side_effect=fake_download), \
         patch("pathlib.Path.mkdir"), \
         patch("threading.Thread") as mock_thread:
        app._save_selected()
        mock_thread.call_args.kwargs["target"]()

    assert isinstance(saved["dest"], Path)
    assert "/" not in saved["dest"].name and "?" not in saved["dest"].name
    assert app.status_msg.startswith("✓")
    app._quit_flag = True


def test_tui_playlists_tab_includes_saved_playlists():
    app = make_app()
    app.my_playlists = [{"type": "playlist", "id": "p1", "title": "Mine"}]
    with patch("ytstr.ui.tui.parse_playlists", return_value=[{"name": "Lofi", "url": "http://lofi"}]):
        app._switch_tab(TAB_PLAYLISTS)
    assert ("saved", "Lofi", "http://lofi") in app.items
    app._quit_flag = True
