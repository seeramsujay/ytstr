"""
High-level YouTube Music client wrapping ytmusicapi with unified data models.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import ytmusicapi
from ytmusicapi import YTMusic

from ytstr.core.types import Track
from ytstr.ytm.auth import AuthManager

logger = logging.getLogger(__name__)

# Keywords identifying personalized recommendation sections vs generic global charts
PERSONALIZED_KEYWORDS = {
    "listen again",
    "quick picks",
    "mixed for you",
    "from your library",
    "forgotten favorites",
    "your daily discover",
    "albums for you",
    "fresh finds",
    "listen together",
    "similar to",
    "recommended",
    "fans of",
}


class YouTubeMusicClient:
    """Interacts with YouTube Music API for recommendations, browsing, and search."""

    def __init__(self, auth_manager: Optional[AuthManager] = None):
        self.auth_manager = auth_manager or AuthManager()
        self._ytm: Optional[YTMusic] = None
        self._init_ytm()

    def _init_ytm(self) -> None:
        """Initialize authenticated or fallback public ytmusicapi instance."""
        auth_file = self.auth_manager.get_auth_filepath()
        if auth_file:
            try:
                self._ytm = YTMusic(auth_file)
                return
            except Exception as e:
                logger.debug("Failed initializing authenticated YTMusic: %s", e)
        # Fallback to unauthenticated public client
        try:
            self._ytm = YTMusic()
        except Exception as e:
            logger.debug("Failed initializing public YTMusic: %s", e)
            self._ytm = None

    @property
    def is_authenticated(self) -> bool:
        """Return True if user is authenticated with personal Google session."""
        return self.auth_manager.is_authenticated()

    def get_home_sections(self, limit: int = 8, personalized_only: bool = True) -> List[Dict[str, Any]]:
        """
        Fetch YouTube Music home feed sections.
        If personalized_only is True, filters to user-specific sections (Listen Again, Quick Picks, etc.).

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
            title_lower = title.lower()

            if personalized_only and self.is_authenticated:
                is_personal = any(k in title_lower for k in PERSONALIZED_KEYWORDS) or "for you" in title_lower
                if not is_personal and "hits" in title_lower:
                    continue

            contents = section.get("contents", [])
            if not isinstance(contents, list):
                continue

            items: List[Any] = []
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
                                "id": str(pl_id),
                                "title": item.get("title", "Untitled Playlist"),
                                "count": item.get("itemCount") or item.get("count"),
                                "thumbnails": item.get("thumbnails", []),
                            })
                except Exception:
                    continue

            if items:
                sections.append({"title": title, "items": items})

        return sections

    def get_personalized_feed(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Convenience alias for get_home_sections with personalized filtering enabled."""
        return self.get_home_sections(limit=limit, personalized_only=True)

    def get_library_playlists(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch all playlists saved in the user's personal YouTube Music library."""
        if not self._ytm or not self.is_authenticated:
            return []

        playlists: List[Dict[str, Any]] = []
        try:
            raw_pls = self._ytm.get_library_playlists(limit=limit)
            if isinstance(raw_pls, list):
                for p in raw_pls:
                    if not p or not isinstance(p, dict):
                        continue
                    pl_id = p.get("playlistId")
                    if not pl_id:
                        continue
                    title = p.get("title", "Untitled Playlist")
                    count = p.get("count")
                    playlists.append({
                        "type": "playlist",
                        "id": str(pl_id),
                        "title": str(title),
                        "count": count,
                        "description": f"{count} tracks" if count else "Playlist",
                    })
        except Exception:
            pass
        return playlists

    def get_user_playlists(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Convenience alias for get_library_playlists."""
        return self.get_library_playlists(limit=limit)

    def get_liked_songs(self, limit: int = 100) -> List[Track]:
        """Fetch user's Liked Music tracks."""
        if not self._ytm or not self.is_authenticated:
            return []

        tracks: List[Track] = []
        try:
            liked = self._ytm.get_liked_songs(limit=limit)
            if isinstance(liked, dict):
                raw_tracks = liked.get("tracks", [])
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

    def get_charts(self, country: str = "US") -> List[Dict[str, Any]]:
        """Fetch popular trending charts."""
        if not self._ytm:
            return []

        chart_sections: List[Dict[str, Any]] = []
        try:
            charts = self._ytm.get_charts(country=country)
            if not isinstance(charts, dict):
                return []
            for key in ["videos", "genres"]:
                entries = charts.get(key)
                if not isinstance(entries, list) or not entries:
                    continue
                items: List[Any] = []
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

    def search(self, query: str, limit: int = 25) -> List[Track]:
        """Convenience alias for search_tracks."""
        return self.search_tracks(query, filter_type="songs", limit=limit)

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
        """Get continuous radio / recommendations seeded by a track."""
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

    def _parse_item_to_track(self, item: Optional[Dict[str, Any]]) -> Optional[Track]:
        """Convert a raw ytmusicapi dictionary into a strongly typed Track object."""
        if not item or not isinstance(item, dict):
            return None

        video_id = item.get("videoId")
        if not video_id:
            return None

        title = item.get("title", "Unknown Title")
        if isinstance(title, dict):
            title = title.get("text", "Unknown Title")

        # Extract artists
        artist_names: List[str] = []
        artists_data = item.get("artists")
        if isinstance(artists_data, list):
            for a in artists_data:
                if isinstance(a, dict) and "name" in a:
                    artist_names.append(str(a["name"]))
                elif isinstance(a, str):
                    artist_names.append(a)
        artist_str = ", ".join(artist_names).strip()

        # Parse duration
        duration_sec = 0.0
        if "duration_seconds" in item and item["duration_seconds"]:
            try:
                duration_sec = float(item["duration_seconds"])
            except (ValueError, TypeError):
                pass
        elif "duration" in item and item["duration"]:
            try:
                parts = str(item["duration"]).split(":")
                if len(parts) == 2:
                    duration_sec = int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:
                    duration_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            except (ValueError, TypeError):
                pass

        # Thumbnail URL
        thumb_url = None
        thumbs = item.get("thumbnails")
        if isinstance(thumbs, list) and thumbs:
            last_thumb = thumbs[-1]
            if isinstance(last_thumb, dict):
                thumb_url = last_thumb.get("url")

        return Track(
            id=str(video_id),
            title=str(title) if title else "Unknown Title",
            artist=artist_str if artist_str else None,
            duration_sec=max(0.0, duration_sec),
            url=f"https://www.youtube.com/watch?v={video_id}",
            thumbnail_url=str(thumb_url) if thumb_url else None,
        )
