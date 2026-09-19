"""
Resilient, high-performance MPV Unix Domain Socket IPC client and process supervisor.
Features persistent socket connections, thread-safe request-response multiplexing,
automatic reconnection with backpressure recovery, and typed property queries.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


class MPVIPCClient:
    """
    Thread-safe, persistent Unix Domain Socket IPC client for mpv.

    Maintains an active socket connection across commands to eliminate kernel
    socket churn and minimize latency, with automatic reconnection and fallback.
    """

    def __init__(self, socket_path: str, default_timeout: float = 1.0):
        self.socket_path = socket_path
        self.default_timeout = default_timeout
        self._sock: Optional[socket.socket] = None
        self._lock = threading.RLock()
        self._request_counter = 0
        self._buffer = b""

    def _ensure_connected(self) -> bool:
        """Ensure the internal socket is connected, reconnecting if needed."""
        if self._sock is not None:
            return True

        if not os.path.exists(self.socket_path):
            return False

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.default_timeout)
            sock.connect(self.socket_path)
            self._sock = sock
            self._buffer = b""
            return True
        except (socket.error, OSError):
            self._close_socket()
            return False

    def _close_socket(self) -> None:
        """Safely close active socket and reset internal buffers."""
        if self._sock is not None:
            try:
                self._sock.close()
            except (socket.error, OSError):
                pass
            self._sock = None
        self._buffer = b""

    def close(self) -> None:
        """Close the underlying IPC client socket."""
        with self._lock:
            self._close_socket()

    def __enter__(self) -> MPVIPCClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def send_command(
        self,
        cmd: Sequence[Any],
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Send a JSON IPC command to the mpv socket and return the response.

        Args:
            cmd: Command list, e.g. ["get_property", "playback-time"]
            timeout: Optional socket timeout override in seconds.

        Returns:
            Decoded JSON response dict (containing 'error', 'data', etc.) or None on error.
        """
        with self._lock:
            effective_timeout = timeout if timeout is not None else self.default_timeout

            # Attempt send up to 2 times (initial attempt + 1 reconnect retry)
            for attempt in range(2):
                if not self._ensure_connected():
                    return None

                try:
                    assert self._sock is not None
                    self._sock.settimeout(effective_timeout)
                    self._request_counter += 1
                    req_id = self._request_counter

                    payload = json.dumps({"command": list(cmd), "request_id": req_id}) + "\n"
                    self._sock.sendall(payload.encode("utf-8"))

                    # Read until we receive response with matching request_id
                    start_time = time.monotonic()
                    while True:
                        # Process all buffered complete lines first
                        while b"\n" in self._buffer:
                            line_raw, self._buffer = self._buffer.split(b"\n", 1)
                            line = line_raw.decode("utf-8", errors="ignore").strip()
                            if not line:
                                continue
                            try:
                                resp = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            # Match on request_id if present
                            if resp.get("request_id") == req_id:
                                return resp
                            if "error" in resp and "request_id" not in resp:
                                # Non-tagged response fallback
                                return resp
                            # Skip asynchronous event lines (e.g. property-change)

                        # Only read from socket if buffer has no complete lines left
                        elapsed = time.monotonic() - start_time
                        remaining_time = effective_timeout - elapsed
                        if remaining_time <= 0:
                            break

                        self._sock.settimeout(max(0.01, remaining_time))
                        chunk = self._sock.recv(4096)
                        if not chunk:
                            # Socket closed by peer
                            self._close_socket()
                            break
                        self._buffer += chunk

                except (socket.timeout, TimeoutError):
                    return None
                except (socket.error, OSError):
                    # Connection dropped or broken pipe: close socket and retry once
                    self._close_socket()
                    if attempt == 1:
                        return None

            return None

    def get_property(self, prop: str, default: Any = None) -> Any:
        """Query raw property value from mpv."""
        res = self.send_command(["get_property", prop])
        if res and res.get("error") == "success":
            data = res.get("data")
            return data if data is not None else default
        return default

    def get_float_property(self, prop: str, default: float = 0.0) -> float:
        """Query numeric property as float with safe fallback against None or parse failure."""
        val = self.get_property(prop)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool_property(self, prop: str, default: bool = False) -> bool:
        """Query property as boolean with safe fallback against None."""
        val = self.get_property(prop)
        if val is None:
            return default
        return bool(val)

    def get_int_property(self, prop: str, default: int = -1) -> int:
        """Query property as integer with safe fallback against None."""
        val = self.get_property(prop)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_str_property(self, prop: str, default: str = "") -> str:
        """Query property as string with safe fallback against None."""
        val = self.get_property(prop)
        if val is None:
            return default
        return str(val)

    def get_properties_batch(self, props: Sequence[str]) -> Dict[str, Any]:
        """
        Query multiple properties over the persistent connection.

        Returns a dictionary mapping property names to their retrieved values (or None).
        """
        with self._lock:
            results: Dict[str, Any] = {}
            for prop in props:
                results[prop] = self.get_property(prop)
            return results

    def set_property(self, prop: str, value: Any) -> bool:
        """Set a property value on mpv."""
        res = self.send_command(["set_property", prop, value])
        return bool(res and res.get("error") == "success")

    def cycle_pause(self) -> bool:
        """Toggle play/pause state."""
        res = self.send_command(["cycle", "pause"])
        return bool(res and res.get("error") == "success")

    def adjust_volume(self, delta: float) -> bool:
        """Adjust volume by positive or negative step."""
        res = self.send_command(["add", "volume", delta])
        return bool(res and res.get("error") == "success")

    def seek(self, seconds: float, mode: str = "relative") -> bool:
        """Seek forward or backward in playback stream."""
        res = self.send_command(["seek", seconds, mode])
        return bool(res and res.get("error") == "success")

    def load_file(self, file_path_or_url: str, mode: str = "replace") -> bool:
        """
        Load media file or URL into mpv.

        Args:
            file_path_or_url: Local file path or streaming URL.
            mode: 'replace', 'append', or 'append-play'.
        """
        res = self.send_command(["loadfile", file_path_or_url, mode])
        return bool(res and res.get("error") == "success")

    def playlist_next(self) -> bool:
        """Advance to next track in mpv playlist."""
        res = self.send_command(["playlist-next"])
        return bool(res and res.get("error") == "success")

    def playlist_prev(self) -> bool:
        """Go back to previous track in mpv playlist."""
        res = self.send_command(["playlist-prev"])
        return bool(res and res.get("error") == "success")

    def playlist_remove(self, index: int) -> bool:
        """Remove a track index from mpv playlist."""
        res = self.send_command(["playlist-remove", index])
        return bool(res and res.get("error") == "success")

    def stop(self) -> bool:
        """Stop playback immediately."""
        res = self.send_command(["stop"])
        return bool(res and res.get("error") == "success")


def spawn_mpv_process(
    ipc_socket: str,
    raw_pcm_mode: bool = False,
    volume: int = 100,
) -> subprocess.Popen:
    """
    Launch an optimized mpv subprocess with Unix IPC enabled.

    Args:
        ipc_socket: Path to the UNIX IPC domain socket.
        raw_pcm_mode: True to accept 16-bit 44.1kHz PCM over stdin, False for standard media.
        volume: Starting volume (0-100).

    Returns:
        subprocess.Popen instance.
    """
    # Remove stale socket if exists
    if os.path.exists(ipc_socket):
        try:
            os.unlink(ipc_socket)
        except OSError:
            pass

    cmd = [
        "mpv",
        f"--input-ipc-server={ipc_socket}",
        "--no-video",
        "--idle=yes",
        f"--volume={volume}",
        "--term-osd=no",
        "--really-quiet",
    ]

    if raw_pcm_mode:
        cmd.extend([
            "--demuxer=rawaudio",
            "--demuxer-rawaudio-format=s16le",
            "--demuxer-rawaudio-rate=44100",
            "--demuxer-rawaudio-channels=2",
            "-",
        ])
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
