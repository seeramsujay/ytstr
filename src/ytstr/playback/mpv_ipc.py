"""
Resilient MPV Unix IPC socket client and process supervisor.
"""
import json
import os
import socket
import subprocess
import time
from typing import Any, List, Optional


class MPVIPCClient:
    """Communicates with mpv via Unix Domain Socket IPC."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    def send_command(self, cmd: List[Any], timeout: float = 1.0) -> Optional[dict]:
        """
        Send a JSON IPC command to the mpv socket and return the response.

        Args:
            cmd: Command list, e.g. ["get_property", "playback-time"]
            timeout: Socket timeout in seconds.

        Returns:
            Decoded JSON dictionary or None on error.
        """
        if not os.path.exists(self.socket_path):
            return None

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(timeout)
                client.connect(self.socket_path)
                payload = json.dumps({"command": cmd}) + "\n"
                client.sendall(payload.encode("utf-8"))
                response_data = b""
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk
                    if b"\n" in chunk:
                        break
                lines = response_data.decode("utf-8", errors="ignore").strip().splitlines()
                for line in lines:
                    try:
                        parsed = json.loads(line)
                        if "error" in parsed:
                            return parsed
                    except json.JSONDecodeError:
                        continue
        except (socket.error, OSError, socket.timeout):
            return None
        return None

    def get_property(self, prop: str) -> Any:
        """Query property value from mpv."""
        res = self.send_command(["get_property", prop])
        if res and res.get("error") == "success":
            return res.get("data")
        return None

    def set_property(self, prop: str, value: Any) -> bool:
        """Set property on mpv."""
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

    def load_file(self, file_path_or_url: str, mode: str = "replace") -> bool:
        """
        Load media file or URL into mpv.

        Args:
            file_path_or_url: Local file path or streaming URL.
            mode: 'replace', 'append', or 'append-play'.
        """
        res = self.send_command(["loadfile", file_path_or_url, mode])
        return bool(res and res.get("error") == "success")

    def stop(self) -> bool:
        """Stop playback."""
        res = self.send_command(["stop"])
        return bool(res and res.get("error") == "success")


def spawn_mpv_process(
    ipc_socket: str,
    raw_pcm_mode: bool = False,
    volume: int = 100,
) -> subprocess.Popen:
    """
    Launch an mpv subprocess with Unix IPC enabled.

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

    mpv_cmd = [
        "mpv",
        "--no-video",
        "--msg-level=all=no",
        f"--input-ipc-server={ipc_socket}",
        f"--volume={volume}",
    ]

    if raw_pcm_mode:
        mpv_cmd.extend([
            "--demuxer=rawaudio",
            "--demuxer-rawaudio-channels=2",
            "--demuxer-rawaudio-format=s16le",
            "--demuxer-rawaudio-rate=44100",
            "-",
        ])
    else:
        mpv_cmd.extend([
            "--gapless-audio=yes",
            "--idle=yes",
        ])

    proc = subprocess.Popen(
        mpv_cmd,
        stdin=subprocess.PIPE if raw_pcm_mode else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait briefly for the IPC socket to be ready
    for _ in range(50):
        if os.path.exists(ipc_socket):
            break
        time.sleep(0.05)

    return proc
