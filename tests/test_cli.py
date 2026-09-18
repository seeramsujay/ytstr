"""
Unit tests for CLI argument routing and command execution.
"""
from unittest.mock import MagicMock, patch
from ytstr.cli import main


def test_cli_version(capsys):
    ret = main(["--version"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "ytstr v" in captured.out


def test_cli_help(capsys):
    ret = main(["--help"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "usage: ytstr" in captured.out


def test_cli_list(capsys):
    with patch("ytstr.cli.parse_playlists", return_value=[{"name": "Lofi", "url": "http://lofi"}]):
        ret = main(["--list"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Lofi" in captured.out
