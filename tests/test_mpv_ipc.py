"""
Unit tests for persistent, thread-safe MPV IPC Client.
"""
import json
import socket
import threading
import time
from unittest.mock import MagicMock, patch
import pytest

from ytstr.playback.mpv_ipc import MPVIPCClient, spawn_mpv_process


def test_mpv_ipc_typed_queries_mock():
    client = MPVIPCClient("/tmp/dummy.sock")
    with patch.object(client, "send_command") as mock_cmd:
        # Float query
        mock_cmd.return_value = {"error": "success", "data": 42.5}
        assert client.get_float_property("time-pos") == 42.5

        # Float query with fallback on None or error
        mock_cmd.return_value = {"error": "property unavailable"}
        assert client.get_float_property("time-pos", default=10.0) == 10.0

        # Bool query
        mock_cmd.return_value = {"error": "success", "data": True}
        assert client.get_bool_property("pause") is True

        # Int query
        mock_cmd.return_value = {"error": "success", "data": 3}
        assert client.get_int_property("playlist-pos") == 3

        # String query
        mock_cmd.return_value = {"error": "success", "data": "opus"}
        assert client.get_str_property("audio-codec-name") == "opus"


def test_mpv_ipc_high_level_controls():
    client = MPVIPCClient("/tmp/dummy.sock")
    with patch.object(client, "send_command") as mock_cmd:
        mock_cmd.return_value = {"error": "success"}

        client.seek(15.0, "relative")
        mock_cmd.assert_called_with(["seek", 15.0, "relative"])

        client.playlist_next()
        mock_cmd.assert_called_with(["playlist-next"])

        client.playlist_prev()
        mock_cmd.assert_called_with(["playlist-prev"])

        client.playlist_remove(2)
        mock_cmd.assert_called_with(["playlist-remove", 2])

        client.cycle_pause()
        mock_cmd.assert_called_with(["cycle", "pause"])

        client.adjust_volume(5.0)
        mock_cmd.assert_called_with(["add", "volume", 5.0])


def test_mpv_ipc_real_unix_socket_request_matching(tmp_path):
    sock_path = str(tmp_path / "test_mpv.sock")

    # Mock server handling mpv json-ipc protocol
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)

    def server_thread():
        conn, _ = server.accept()
        f = conn.makefile("r", encoding="utf-8")
        out = conn.makefile("w", encoding="utf-8")

        while True:
            line = f.readline()
            if not line:
                break
            req = json.loads(line)
            req_id = req.get("request_id")
            # First send an async event to test client ignores events
            event_line = json.dumps({"event": "playback-restart"}) + "\n"
            out.write(event_line)
            out.flush()

            # Now send response matching request_id
            cmd = req.get("command", [])
            if cmd and cmd[0] == "get_property" and cmd[1] == "time-pos":
                resp = {"error": "success", "data": 12.34, "request_id": req_id}
            else:
                resp = {"error": "success", "data": None, "request_id": req_id}

            out.write(json.dumps(resp) + "\n")
            out.flush()

        conn.close()
        server.close()

    t = threading.Thread(target=server_thread, daemon=True)
    t.start()

    time.sleep(0.05)
    client = MPVIPCClient(sock_path, default_timeout=2.0)

    # Query time-pos
    time_pos = client.get_float_property("time-pos")
    assert time_pos == 12.34

    # Close client
    client.close()
