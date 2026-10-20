"""
Tests for mode separation (No-Mix / Stream / Light Mix / Auto-DJ), the out-of-process
yt-dlp downloader, mpv option probing and lazy imports that keep RAM low.
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from ytstr.core.types import Track
from ytstr.downloader import ytdlp
from ytstr.downloader.ytdlp import Downloader
from ytstr.playback import mpv_ipc

REAL_RUN = Downloader._run  # Captured before the autouse fixture stubs it out


# ---------------------------------------------------------------------------
# Downloader (yt-dlp in a subprocess)
# ---------------------------------------------------------------------------
def test_fetch_playlist_tracks_parses_flat_json():
    payload = {"entries": [
        {"id": "aaaaaaaaaaa", "title": "One", "uploader": "Artist", "duration": 61},
        {"id": None, "title": "broken"},
        {"id": "bbbbbbbbbbb", "title": "Two", "duration": "bad"},
    ]}
    calls = []
    with patch.object(Downloader, "_run", lambda self, args, timeout: calls.append(args) or json.dumps(payload)):
        tracks = Downloader().fetch_playlist_tracks("lofi beats")
    assert [t.id for t in tracks] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert tracks[0].artist == "Artist" and tracks[0].duration_sec == 61.0
    assert tracks[1].duration_sec == 0.0
    assert calls[0][-1] == "ytsearch10:lofi beats"
    assert "--flat-playlist" in calls[0]


def test_get_direct_stream_url_returns_first_url_line():
    with patch.object(Downloader, "_run", lambda self, args, timeout: "https://a/stream\nhttps://b\n"):
        assert Downloader().get_direct_stream_url("abc") == "https://a/stream"
    with patch.object(Downloader, "_run", lambda self, args, timeout: None):
        assert Downloader().get_direct_stream_url("abc") is None


def test_download_track_escapes_template_percent(tmp_path):
    dest = tmp_path / "100% hits.opus"
    seen = {}

    def fake_run(self, args, timeout):
        seen["outtmpl"] = args[args.index("--output") + 1]
        dest.write_bytes(b"x" * 2048)
        return ""

    with patch.object(Downloader, "_run", fake_run):
        assert Downloader().download_track(Track(id="abc", title="t"), dest) is True
    assert seen["outtmpl"].endswith("100%% hits.opus")


def test_run_uses_subprocess_and_silences_all_output():
    proc = MagicMock()
    proc.communicate.return_value = (b"out", b"")
    proc.returncode = 0
    with patch("subprocess.Popen", return_value=proc) as popen:
        assert REAL_RUN(Downloader(), ["--version"], 5) == "out"
    cmd = popen.call_args.args[0]
    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
    assert "--no-progress" in cmd and "--quiet" in cmd
    kwargs = popen.call_args.kwargs
    assert kwargs["stdin"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL


def test_run_failure_and_close():
    proc = MagicMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 1
    d = Downloader()
    with patch("subprocess.Popen", return_value=proc):
        assert REAL_RUN(d, ["x"], 5) is None
        d.close()
        assert REAL_RUN(d, ["x"], 5) is None  # Closed downloaders never spawn again


def test_frozen_build_reinvokes_itself_as_ytdlp():
    with patch.object(sys, "frozen", True, create=True):
        assert ytdlp.ytdlp_command() == [sys.executable, ytdlp.YTDLP_WORKER_FLAG]


# ---------------------------------------------------------------------------
# mpv options
# ---------------------------------------------------------------------------
def test_lean_mpv_options_only_passes_supported_flags():
    supported = frozenset({"terminal", "osc", "load-console", "demuxer-max-bytes", "ytdl"})
    with patch.object(mpv_ipc, "supported_mpv_options", return_value=supported):
        direct = mpv_ipc.lean_mpv_options(raw_pcm_mode=False)
        raw = mpv_ipc.lean_mpv_options(raw_pcm_mode=True)
    assert direct == ["--terminal=no", "--osc=no", "--load-console=no", "--demuxer-max-bytes=8MiB"]
    assert raw == direct + ["--ytdl=no"]  # yt-dlp hook only kept where URLs may need it


def test_direct_mpv_never_reads_the_terminal():
    with patch("subprocess.Popen") as popen, \
         patch.object(mpv_ipc, "supported_mpv_options", return_value=frozenset()):
        mpv_ipc.spawn_mpv_process("/tmp/ytstr_test.sock", raw_pcm_mode=False)
    assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL


# ---------------------------------------------------------------------------
# Mode separation
# ---------------------------------------------------------------------------
def test_direct_modes_and_cli_do_not_load_dsp_or_heavy_libraries():
    code = (
        "import sys, ytstr.cli, ytstr.playback.direct, ytstr.core.player;"
        "heavy = [m for m in ('pydub', 'yt_dlp', 'ytmusicapi', 'ytstr.playback.dj_player', 'ytstr.ui.tui')"
        " if m in sys.modules]; print(heavy)"
    )
    src = str(Path(__file__).resolve().parent.parent / "src")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"PYTHONPATH": src, "PATH": "/usr/bin:/bin"}, check=True)
    assert out.stdout.strip() == "[]"


def make_dj(light_mix):
    from ytstr.playback.dj_player import DJPlayer

    return DJPlayer([Track(id="a", title="A"), Track(id="b", title="B")], MagicMock(), MagicMock(),
                    light_mix=light_mix, crossfade_sec=3.0)


def test_light_mix_and_auto_dj_reserve_their_own_tail():
    light, auto = make_dj(True), make_dj(False)
    assert light.mode_label == "Light Mix" and auto.mode_label == "Auto-DJ"
    assert light._tail_reserve_ms() == 3000
    assert auto._tail_reserve_ms() == 9000  # Longest Auto-DJ transition (blend) at 3s fade
    auto.mix_enabled = False
    assert auto._tail_reserve_ms() == 0  # Unmixed handover plays the track to its end


def test_switching_mix_mode_discards_the_prerendered_transition():
    from ytstr.playback.dj_player import PlannedMix

    dj = make_dj(False)
    dj._planned_mix = PlannedMix(0, "b", False, "melt", MagicMock(), 7000)
    dj.light_mix = True
    assert dj._planned_mix is None
    dj._planned_mix = PlannedMix(0, "b", True, "fade", MagicMock(), 3000)
    dj.light_mix = True  # Unchanged mode keeps it
    assert dj._planned_mix is not None
    dj.mix_enabled = False
    assert dj._planned_mix is None


def test_tui_badge_shows_active_and_pending_mode():
    from tests.test_regressions import make_app

    app = make_app()
    assert app._mode_badge() == "Direct Low-RAM"  # Idle: just the selected mode
    app.active_engine = "direct"
    app._direct_mode_idx = 0
    assert app._mode_badge() == "▶ Direct Low-RAM"
    app.mode_idx = 1  # Selected Light Mix while a direct track is still playing
    assert app._mode_badge() == "▶ Direct Low-RAM → Light Mix"
    app.dj_player = make_dj(True)
    app.active_engine = "dj"
    assert app._mode_badge() == "▶ Light Mix"
    app.mode_idx = 3
    assert app._mode_badge() == "▶ Light Mix → Auto-DJ (Spectral)"
    app._quit_flag = True


def test_tui_switch_from_dj_to_direct_finishes_song_unmixed():
    from tests.test_regressions import make_app

    app = make_app()
    app.dj_player = make_dj(False)
    app.active_engine = "dj"
    app.now_playing = "A"
    app.mode_idx = 3
    app._handle_mode_switch()  # -> 0 (Direct Low-RAM)
    assert app.mode_idx == 0
    assert app.dj_player.mix_enabled is False
    assert "unmixed" in app.status_msg
    app._quit_flag = True
