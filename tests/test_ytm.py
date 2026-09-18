"""
Unit tests for YouTube Music client, authentication, and GUI components.
"""
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch

from ytstr.core.types import Track
from ytstr.ytm.auth import AuthManager
from ytstr.ytm.client import YouTubeMusicClient
from ytstr.ytm.gui import YTMDesktopApp


def test_auth_manager_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        auth_file = Path(tmpdir) / "test_auth.json"
        auth = AuthManager(auth_path=auth_file)

        assert not auth.is_authenticated()
        assert auth.get_auth_filepath() is None

        # Simulate authenticated JSON file
        auth_file.write_text('{"cookie": "SAPISID=123; HSID=456"}')
        assert auth.is_authenticated()
        assert auth.get_auth_filepath() == str(auth_file)

        auth.logout()
        assert not auth.is_authenticated()
        assert not auth_file.exists()


def test_ytm_client_parse_item():
    client = YouTubeMusicClient()
    raw_item = {
        "videoId": "abc123xyz",
        "title": "Starboy",
        "artists": [{"name": "The Weeknd"}, {"name": "Daft Punk"}],
        "duration_seconds": 230,
        "thumbnails": [{"url": "https://example.com/thumb.jpg", "width": 120, "height": 120}],
    }
    track = client._parse_item_to_track(raw_item)
    assert isinstance(track, Track)
    assert track.id == "abc123xyz"
    assert track.title == "Starboy"
    assert track.artist == "The Weeknd, Daft Punk"
    assert track.duration_sec == 230.0
    assert track.web_url == "https://www.youtube.com/watch?v=abc123xyz"


def test_gui_initialization():
    root = tk.Tk()
    root.withdraw()
    try:
        app = YTMDesktopApp(root)
        assert app.root == root
        assert app.mode_var.get() == "Direct Low-RAM (--no-mix)"
    finally:
        root.destroy()
