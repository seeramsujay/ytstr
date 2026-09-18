"""
yt-dlp wrapper for metadata extraction, streaming URL resolution, and bounded downloading.
"""
from pathlib import Path
from typing import Dict, List, Optional
import yt_dlp

from ytstr.core.types import Track


class Downloader:
    """Wrapper for yt_dlp operations."""

    def __init__(self, quiet: bool = True):
        self.quiet = quiet

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
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(query_url, download=False)
            if not res:
                return tracks

            if "entries" in res:
                for entry in res["entries"]:
                    if not entry:
                        continue
                    video_id = entry.get("id")
                    if video_id:
                        tracks.append(
                            Track(
                                id=video_id,
                                title=entry.get("title", "Unknown Title"),
                                artist=entry.get("uploader") or entry.get("channel"),
                                duration_sec=float(entry.get("duration") or 0.0),
                                url=f"https://www.youtube.com/watch?v={video_id}",
                            )
                        )
            else:
                video_id = res.get("id")
                if video_id:
                    tracks.append(
                        Track(
                            id=video_id,
                            title=res.get("title", "Unknown Title"),
                            artist=res.get("uploader") or res.get("channel"),
                            duration_sec=float(res.get("duration") or 0.0),
                            url=f"https://www.youtube.com/watch?v={video_id}",
                        )
                    )

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
            "noprogress": True,
            "overwrites": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track.web_url])
            return dest_path.exists() and dest_path.stat().st_size > 1024
        except Exception:
            return False
