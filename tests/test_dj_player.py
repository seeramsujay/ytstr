"""
Unit tests for DJPlayer engine, bounded hysteresis, and dynamic queue management.
"""
from unittest.mock import MagicMock, patch
from ytstr.core.types import Track
from ytstr.playback.dj_player import DJPlayer, HIGH_WATERMARK_SEC, LOW_WATERMARK_SEC, STREAM_CHUNK_SEC


def test_dj_player_init_and_queue_ops():
    t1 = Track(id="1", title="Song 1", duration_sec=180.0)
    t2 = Track(id="2", title="Song 2", duration_sec=210.0)
    t3 = Track(id="3", title="Song 3", duration_sec=240.0)

    cache_mgr = MagicMock()
    downloader = MagicMock()

    player = DJPlayer(
        tracks=[t1, t2],
        cache_manager=cache_mgr,
        downloader=downloader,
        light_mix=False,
    )

    assert len(player.tracks) == 2
    assert player.playing_idx == 0
    assert player.downloaded_idx == -1

    # Test appending new tracks (e.g. from radio fetch)
    player.append_tracks([t3, t1])  # t1 is duplicate, should be skipped
    assert len(player.tracks) == 3
    assert player.tracks[2].id == "3"

    # Test removing upcoming track
    ok = player.remove_track(2)
    assert ok is True
    assert len(player.tracks) == 2

    # Cannot remove currently playing track via remove_track
    ok_curr = player.remove_track(0)
    assert ok_curr is False
    assert len(player.tracks) == 2


def test_dj_player_playback_status_timeline_mapping():
    t1 = Track(id="1", title="Song 1", duration_sec=180.0)
    t2 = Track(id="2", title="Song 2", duration_sec=200.0)

    cache_mgr = MagicMock()
    downloader = MagicMock()

    player = DJPlayer(
        tracks=[t1, t2],
        cache_manager=cache_mgr,
        downloader=downloader,
    )

    # Populate mock timeline
    player.timeline = [
        {
            "idx": 0,
            "track": t1,
            "stream_start_s": 0.0,
            "duration": 180.0,
            "transition": "",
        },
        {
            "idx": 1,
            "track": t2,
            "stream_start_s": 176.0,
            "duration": 200.0,
            "transition": "bass_swap",
        },
    ]

    mock_ipc = MagicMock()
    player.ipc = mock_ipc

    # Case 1: Time in track 0 (e.g. 50s)
    mock_ipc.get_property.side_effect = lambda prop: 50.0 if prop == "playback-time" else False
    st1 = player.get_playback_status()
    assert st1["index"] == 0
    assert st1["track"] == t1
    assert st1["time_pos"] == 50.0
    assert st1["duration"] == 180.0

    # Case 2: Time in track 1 (e.g. 190s -> 14s into track 1)
    mock_ipc.get_property.side_effect = lambda prop: 190.0 if prop == "playback-time" else False
    st2 = player.get_playback_status()
    assert st2["index"] == 1
    assert st2["track"] == t2
    assert abs(st2["time_pos"] - 14.0) < 0.1
    assert st2["duration"] == 200.0
    assert st2["transition"] == "bass_swap"


def test_bounded_hysteresis_constants():
    assert STREAM_CHUNK_SEC == 6.0
    assert HIGH_WATERMARK_SEC > LOW_WATERMARK_SEC
    assert LOW_WATERMARK_SEC >= STREAM_CHUNK_SEC
