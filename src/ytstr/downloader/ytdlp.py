"""
yt-dlp wrapper for metadata extraction, streaming URL resolution, and bounded downloading.

yt-dlp runs in short-lived subprocesses instead of being imported: importing it costs
~25 MB of resident memory and every extraction grows the heap further (memory Python
never returns to the OS). A subprocess releases everything as soon as it exits, and its
progress output can never leak onto the TUI.
"""
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ytstr.core.types import Track

# argv[1] flag that makes a frozen (PyInstaller) ytstr binary act as the yt-dlp CLI
YTDLP_WORKER_FLAG = "--ytstr-ytdlp-worker"

METADATA_TIMEOUT_SEC = 120
STREAM_URL_TIMEOUT_SEC = 60
DOWNLOAD_TIMEOUT_SEC = 600


def ytdlp_command() -> List[str]:
    """Command prefix that runs yt-dlp with this interpreter's installation."""
    if getattr(sys, "frozen", False):
        return [sys.executable, YTDLP_WORKER_FLAG]
    return [sys.executable, "-m", "yt_dlp"]


def run_ytdlp_worker(argv: List[str]) -> int:
    """Entry point for YTDLP_WORKER_FLAG: run the bundled yt-dlp CLI in this process."""
    import yt_dlp

    try:
        yt_dlp.main(argv)
    except SystemExit as e:
        return int(e.code or 0)
    return 0


class Downloader:
    """Wrapper for yt-dlp operations with safe parsing and fallbacks."""

    def __init__(self, quiet: bool = True):
        self.quiet = quiet
        self._procs: Set[subprocess.Popen] = set()
        self._procs_lock = threading.Lock()
        self._closed = False

    def _run(self, args: List[str], timeout: float) -> Optional[str]:
        """Run yt-dlp with args; return stdout on success, None on any failure."""
        cmd = ytdlp_command() + ["--no-warnings", "--quiet", "--no-progress", *args]
        with self._procs_lock:
            if self._closed:
                return None
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
            except OSError:
                return None
            self._procs.add(proc)
        try:
            out, _ = proc.communicate(timeout=timeout)
            return out.decode("utf-8", errors="replace") if proc.returncode == 0 else None
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return None
        finally:
            with self._procs_lock:
                self._procs.discard(proc)

    def close(self) -> None:
        """Terminate any in-flight yt-dlp subprocesses (called on shutdown)."""
        with self._procs_lock:
            self._closed = True
            procs = list(self._procs)
        for proc in procs:
            try:
                proc.kill()
            except OSError:
                pass

    @staticmethod
    def _entry_to_track(entry: Optional[Dict[str, Any]]) -> Optional[Track]:
        """Convert a yt-dlp metadata entry into a validated Track object."""
        if not entry or not isinstance(entry, dict):
            return None
        video_id = entry.get("id")
        if not video_id:
            return None

        # Safely parse duration
        duration_raw = entry.get("duration")
        try:
            duration_sec = float(duration_raw) if duration_raw is not None else 0.0
        except (ValueError, TypeError):
            duration_sec = 0.0

        title = entry.get("title") or "Unknown Title"
        artist = entry.get("uploader") or entry.get("channel") or entry.get("artist")

        return Track(
            id=str(video_id),
            title=str(title),
            artist=str(artist) if artist else None,
            duration_sec=max(0.0, duration_sec),
            url=f"https://www.youtube.com/watch?v={video_id}",
        )

    def fetch_playlist_tracks(self, target: str) -> List[Track]:
        """
        Fetch video metadata from YouTube playlist, album, search query, or single video.

        Args:
            target: URL, playlist ID, or search query string.

        Returns:
            List of Track dataclass objects.
        """
        # If not a URL, treat as youtube search query
        query_url = target
        if not (target.startswith("http://") or target.startswith("https://")):
            query_url = f"ytsearch10:{target}"

        out = self._run(["--flat-playlist", "--dump-single-json", query_url], METADATA_TIMEOUT_SEC)
        if not out:
            return []
        try:
            res = json.loads(out)
        except json.JSONDecodeError:
            return []
        if not isinstance(res, dict):
            return []

        tracks: List[Track] = []
        entries = res.get("entries") if "entries" in res else [res]
        for entry in entries or []:
            track = self._entry_to_track(entry)
            if track:
                tracks.append(track)
        return tracks

    def get_direct_stream_url(self, video_id_or_url: str) -> Optional[str]:
        """
        Extract direct audio stream URL (HTTPS/HLS) without downloading media file.

        Args:
            video_id_or_url: YouTube video ID or full watch URL.

        Returns:
            Direct audio stream URL or None if unavailable.
        """
        url = (
            video_id_or_url
            if video_id_or_url.startswith("http")
            else f"https://www.youtube.com/watch?v={video_id_or_url}"
        )
        out = self._run(["--format", "bestaudio/best", "--get-url", "--no-playlist", url], STREAM_URL_TIMEOUT_SEC)
        if not out:
            return None
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        return lines[0] if lines else None

    def download_track(self, track: Track, dest_path: Path) -> bool:
        """
        Download high-quality audio stream to destination path.

        Args:
            track: Track instance to download.
            dest_path: Exact destination path file (e.g. 0.opus).

        Returns:
            True if download succeeded, False otherwise.
        """
        dest_path = Path(dest_path)
        # yt-dlp treats "%" in the output path as a template field
        outtmpl = str(dest_path).replace("%", "%%")
        self._run(
            ["--format", "bestaudio/best", "--output", outtmpl, "--no-playlist", "--no-mtime", track.web_url],
            DOWNLOAD_TIMEOUT_SEC,
        )
        try:
            return dest_path.exists() and dest_path.stat().st_size > 1024
        except OSError:
            return False
