"""
yt-dlp wrapper for metadata extraction, streaming URL resolution, and bounded downloading.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional
import yt_dlp

from ytstr.core.types import Track


class Downloader:
    """Wrapper for yt_dlp operations with safe parsing and fallbacks."""

    def __init__(self, quiet: bool = True):
        self.quiet = quiet

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
        ydl_opts = {
            "extract_flat": True,
            "quiet": self.quiet,
            "no_warnings": True,
            "skip_download": True,
        }

        # If not a URL, treat as youtube search query
        query_url = target
        if not (target.startswith("http://") or target.startswith("https://")):
            query_url = f"ytsearch10:{target}"

        tracks: List[Track] = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(query_url, download=False)
                if not res:
                    return tracks

                if "entries" in res:
                    for entry in res["entries"]:
                        track = self._entry_to_track(entry)
                        if track:
                            tracks.append(track)
                else:
                    track = self._entry_to_track(res)
                    if track:
                        tracks.append(track)
        except Exception:
            return tracks

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
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and "url" in info:
                    return str(info["url"])
        except Exception:
            return None
        return None

    def download_track(self, track: Track, dest_path: Path) -> bool:
        """
        Download high-quality audio stream to destination path.

        Args:
            track: Track instance to download.
            dest_path: Exact destination path file (e.g. 0.opus).

        Returns:
            True if download succeeded, False otherwise.
        """
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(dest_path),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track.web_url])
            return dest_path.exists() and dest_path.stat().st_size > 1024
        except Exception:
            return False
