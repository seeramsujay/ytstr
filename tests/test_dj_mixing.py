"""
End-to-end mixing tests: real ffmpeg decoding and DSP, mpv replaced by a fake clock.

Verifies, for Light Mix and every Auto-DJ transition, that each track is streamed
without gaps or repeated audio, that the incoming track resumes exactly where its
transition ended, and that Light Mix never runs spectral analysis.
"""
import shutil
import subprocess
import threading
from unittest.mock import MagicMock

import pytest

from ytstr.audio import dsp
from ytstr.audio.transitions import transition_window_ms
from ytstr.core.types import Track, TransitionType
from ytstr.playback import dj_player as dj_module
from ytstr.playback.dj_player import DJPlayer

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")

TRACK_SEC = 16
N_TRACKS = 3
FADE_SEC = 2.0


@pytest.fixture(scope="module")
def track_files(tmp_path_factory):
    root = tmp_path_factory.mktemp("tracks")
    files = []
    for i in range(N_TRACKS):
        path = root / f"t{i}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", f"sine=frequency={110 + 70 * i}:duration={TRACK_SEC}",
             "-ac", "2", "-ar", "44100", str(path)],
            check=True,
        )
        files.append(path)
    return files


def run_player(track_files, light_mix, forced_transition=None, timeout=60.0):
    tracks = [Track(id=f"t{i}", title=f"T{i}") for i in range(N_TRACKS)]
    by_id = {t.id: f for t, f in zip(tracks, track_files)}

    cache_mgr = MagicMock()
    cache_mgr.find_cached_file.side_effect = lambda t: by_id[t.id]
    cache_mgr.track_is_cached.return_value = True
    cache_mgr.is_unavailable.return_value = False

    announced = []
    player = DJPlayer(tracks, cache_mgr, MagicMock(), light_mix=light_mix, crossfade_sec=FADE_SEC,
                      on_track_change=lambda i, t, tr: announced.append((i, tr)))
    player._launch_mpv = lambda: None
    player._write_pcm_to_mpv = lambda raw: True
    # Fake mpv clock: always ~10s behind what has been written (steady, healthy buffer)
    player._mpv_time = lambda: max(0.0, player.total_written_s - 10.0)

    analysis_calls = []
    real_select = player.engine.select_transition

    def spy_select(a, b):
        analysis_calls.append(1)
        return forced_transition or real_select(a, b)

    player.engine.select_transition = spy_select

    # Record which source ranges the streaming thread writes (render thread reads windows only)
    reads = {t.id: [] for t in tracks}
    real_chunk = dsp.get_audio_chunk

    def recording_chunk(path, start_s, dur_s):
        if threading.current_thread().name == "ytstr-dj-stream":
            reads[path.rsplit("/", 1)[-1][:-4]].append((round(start_s, 3), round(start_s + dur_s, 3)))
        return real_chunk(path, start_s, dur_s)

    dj_module.get_audio_chunk = recording_chunk
    try:
        worker = threading.Thread(target=player._stream_worker, name="ytstr-dj-stream", daemon=True)
        worker.start()
        while worker.is_alive() and player._stream_idx < N_TRACKS:
            worker.join(timeout=0.1)
            timeout -= 0.1
            assert timeout > 0, "stream worker did not finish"
        # Let the fake clock reach the end so every track is announced
        player._mpv_time = lambda: player.total_written_s
        player._announce_audible(player.total_written_s)
    finally:
        player._quit_flag = True
        dj_module.get_audio_chunk = real_chunk
    return player, reads, announced, analysis_calls


def assert_contiguous(intervals, start, end):
    assert intervals, "track was never streamed"
    assert intervals[0][0] == pytest.approx(start, abs=0.002)
    for (_, a_end), (b_start, _) in zip(intervals, intervals[1:]):
        assert b_start == pytest.approx(a_end, abs=0.002), f"gap/repeat between {a_end} and {b_start}"
    assert intervals[-1][1] == pytest.approx(end, abs=0.002)


def check_geometry(player, reads, expected_type):
    entries = {e["idx"]: e for e in player.timeline}
    resume = 0.0
    for i in range(N_TRACKS):
        dur = entries[i]["duration"]
        nxt = entries.get(i + 1)
        if nxt is not None and nxt["transition"]:
            assert nxt["transition"] == expected_type
            consumed = transition_window_ms(expected_type, int(FADE_SEC * 1000)) / 1000.0
            end = dur - min(consumed, dur)
        else:
            consumed, end = 0.0, dur
        assert_contiguous(reads[f"t{i}"], resume, end)
        resume = consumed


def test_light_mix_never_analyses_and_streams_seamlessly(track_files):
    player, reads, announced, analysis_calls = run_player(track_files, light_mix=True)
    assert analysis_calls == [], "Light Mix must not run spectral analysis"
    check_geometry(player, reads, TransitionType.FADE.value)
    assert [i for i, _ in announced] == [0, 1, 2]
    assert [tr for _, tr in announced] == ["", "fade", "fade"]


@pytest.mark.parametrize("transition", [t.value for t in TransitionType])
def test_auto_dj_transition_streams_seamlessly(track_files, transition):
    player, reads, announced, analysis_calls = run_player(track_files, light_mix=False,
                                                          forced_transition=transition)
    assert len(analysis_calls) == N_TRACKS - 1, "Auto-DJ analyses each boundary once"
    check_geometry(player, reads, transition)
    assert [i for i, _ in announced] == [0, 1, 2]
    assert [tr for _, tr in announced][1:] == [transition, transition]
