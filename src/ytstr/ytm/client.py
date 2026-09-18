"""
High-level YouTube Music client wrapping ytmusicapi with unified data models.
"""
from typing import Any, Dict, List, Optional
import ytmusicapi
from ytmusicapi import YTMusic

from ytstr.core.types import Track
from ytstr.ytm.auth import AuthManager


class YouTubeMusicClient:
    """Interacts with YouTube Music API for recommendations, browsing, and search."""

    def __init__(self, auth_manager: Optional[AuthManager] = None):
        self.auth_manager = auth_manager or AuthManager()
        self._ytm: Optional[YTMusic] = None
        self._init_ytm()

    def _init_ytm(self):
        auth_file = self.auth_manager.get_auth_filepath()
        if auth_file:
            try:
                self._ytm = YTMusic(auth_file)
                return
            except Exception:
                pass
        # Fallback to unauthenticated public client
        try:
            self._ytm = YTMusic()
        except Exception:
            self._ytm = None

    @property
    def is_authenticated(self) -> bool:
        return self.auth_manager.is_authenticated()

    def get_home_sections(self, limit: int = 6) -> List[Dict[str, Any]]:
        """
        Fetch YouTube Music home feed sections (Listen Again, Quick Picks, etc.).

        Returns list of sections: [{"title": str, "items": [Track | dict]}]
        """
        if not self._ytm:
            return []

        sections: List[Dict[str, Any]] = []
        try:
            home_data = self._ytm.get_home(limit=limit)
        except Exception:
            return []

        if not isinstance(home_data, list):
            return []

        for section in home_data:
            if not isinstance(section, dict):
                continue
            title = section.get("title", "Featured")
            contents = section.get("contents", [])
            if not isinstance(contents, list):
                continue

            items = []
            for item in contents:
                if not item or not isinstance(item, dict):
                    continue
                try:
                    track = self._parse_item_to_track(item)
                    if track:
                        items.append(track)
                    else:
                        pl_id = item.get("playlistId") or item.get("browseId")
                        if pl_id:
                            items.append({
                                "type": "playlist",
                                "id": pl_id,
                                "title": item.get("title", "Untitled Playlist"),
                                "thumbnails": item.get("thumbnails", []),
                            })
                except Exception:
                    continue

            if items:
                sections.append({"title": title, "items": items})

        return sections

    def get_charts(self, country: str = "US") -> List[Dict[str, Any]]:
        """Fetch popular trending charts."""
        if not self._ytm:
            return []

        chart_sections = []
        try:
            charts = self._ytm.get_charts(country=country)
            if not isinstance(charts, dict):
                return []
            for key in ["videos", "genres"]:
                entries = charts.get(key)
                if not isinstance(entries, list) or not entries:
                    continue
                items = []
                for item in entries:
                    if not item or not isinstance(item, dict):
                        continue
                    if item.get("playlistId"):
                        items.append({
                            "type": "playlist",
                            "id": item.get("playlistId"),
                            "title": item.get("title", "Top Chart"),
                        })
                    else:
                        t = self._parse_item_to_track(item)
                        if t:
                            items.append(t)
                if items:
                    chart_sections.append({"title": f"Charts: {key.capitalize()}", "items": items})
        except Exception:
            pass
        return chart_sections

    def search_tracks(self, query: str, filter_type: str = "songs", limit: int = 20) -> List[Track]:
        """Search tracks on YouTube Music."""
        if not self._ytm or not query.strip():
            return []

        tracks: List[Track] = []
        try:
            results = self._ytm.search(query, filter=filter_type, limit=limit)
            if isinstance(results, list):
                for r in results:
                    if not r or not isinstance(r, dict):
                        continue
                    t = self._parse_item_to_track(r)
                    if t:
                        tracks.append(t)
        except Exception:
            pass
        return tracks

    def get_playlist_tracks(self, playlist_id: str) -> List[Track]:
        """Extract tracks from a YouTube Music playlist."""
        if not self._ytm:
            return []

        tracks: List[Track] = []
        try:
            playlist = self._ytm.get_playlist(playlist_id, limit=100)
            if isinstance(playlist, dict):
                raw_tracks = playlist.get("tracks", [])
                if isinstance(raw_tracks, list):
                    for item in raw_tracks:
                        if not item or not isinstance(item, dict):
                            continue
                        t = self._parse_item_to_track(item)
                        if t:
                            tracks.append(t)
        except Exception:
            pass
        return tracks

    def get_watch_playlist_tracks(self, video_id: str, limit: int = 25) -> List[Track]:
        """Get infinite radio / recommendations seeded by a track."""
        if not self._ytm:
            return []

        tracks: List[Track] = []
        try:
            radio = self._ytm.get_watch_playlist(videoId=video_id, limit=limit)
            if isinstance(radio, dict):
                raw_tracks = radio.get("tracks", [])
                if isinstance(raw_tracks, list):
                    for item in raw_tracks:
                        if not item or not isinstance(item, dict):
                            continue
                        t = self._parse_item_to_track(item)
                        if t:
                            tracks.append(t)
        except Exception:
            pass
        return tracks

    def _parse_item_to_track(self, item: Any) -> Optional[Track]:
        """Convert a ytmusicapi item dictionary to a Track dataclass."""
        if not item or not isinstance(item, dict):
            return None

        video_id = item.get("videoId")
        if not video_id:
            return None

        title = item.get("title", "Unknown Title")
        artist = None
        artists = item.get("artists")
        if isinstance(artists, list) and artists:
            artist = ", ".join([a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")])
        elif isinstance(artists, str):
            artist = artists

        duration_sec = float(item.get("duration_seconds") or 0.0)
        thumbnails = item.get("thumbnails", [])
        thumb_url = None
        if isinstance(thumbnails, list) and thumbnails:
            last_thumb = thumbnails[-1]
            if isinstance(last_thumb, dict):
                thumb_url = last_thumb.get("url")

        return Track(
            id=video_id,
            title=title,
            artist=artist,
            duration_sec=duration_sec,
            url=f"https://www.youtube.com/watch?v={video_id}",
            thumbnail_url=thumb_url,
        )
