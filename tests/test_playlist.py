"""
Unit tests for playlist parsing, saving, adding, and removing.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from ytstr.core.playlist import add_playlist, parse_playlists, remove_playlist, save_playlists, shuffle_tracks
from ytstr.core.types import Track


def test_parse_and_save_playlists():
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_file = Path(tmpdir) / "playlists"
        with patch("ytstr.core.playlist.PLAYLIST_FILE", fake_file), patch(
            "ytstr.core.playlist.ensure_config_dir"
        ):
            # Save 2 playlists
            items = [
                {"name": "Chill Beats", "url": "https://youtube.com/playlist?list=123"},
                {"name": "Workout", "url": "https://youtube.com/playlist?list=456"},
            ]
            assert save_playlists(items)

            loaded = parse_playlists()
            assert len(loaded) == 2
            assert loaded[0]["name"] == "Chill Beats"
            assert loaded[1]["url"] == "https://youtube.com/playlist?list=456"

            # Add a third
            add_playlist("Rock", "https://youtube.com/playlist?list=789")
            assert len(parse_playlists()) == 3

            # Remove second
            removed = remove_playlist(1)
            assert removed["name"] == "Workout"
            assert len(parse_playlists()) == 2


def test_shuffle_tracks():
    tracks = [Track(id=f"id{i}", title=f"title{i}") for i in range(20)]
    shuffled = shuffle_tracks(tracks)
    assert len(shuffled) == len(tracks)
    assert set(t.id for t in shuffled) == set(t.id for t in tracks)
