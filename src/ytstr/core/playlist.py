"""
Playlist persistence, parsing, and ordering utilities.
"""
import random
from typing import Dict, List, Optional
from ytstr.config import PLAYLIST_FILE, ensure_config_dir
from ytstr.core.types import Track


def parse_playlists() -> List[Dict[str, str]]:
    """Read saved named playlists from ~/.config/ytstr/playlists."""
    ensure_config_dir()
    playlists = []
    try:
        with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "|" not in line:
                    continue
                parts = line.split("|", 1)
                if len(parts) == 2:
                    name, url = parts
                    if name.strip() and url.strip():
                        playlists.append({"name": name.strip(), "url": url.strip()})
    except Exception:
        pass
    return playlists


def save_playlists(playlists: List[Dict[str, str]]) -> bool:
    """Save named playlists list to ~/.config/ytstr/playlists."""
    ensure_config_dir()
    try:
        with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
            for p in playlists:
                f.write(f"{p['name']}|{p['url']}\n")
        return True
    except Exception:
        return False


def add_playlist(name: str, url: str) -> bool:
    """Add a new playlist entry."""
    playlists = parse_playlists()
    playlists.append({"name": name, "url": url})
    return save_playlists(playlists)


def remove_playlist(index: int) -> Optional[Dict[str, str]]:
    """Remove playlist entry by 0-based index."""
    playlists = parse_playlists()
    if 0 <= index < len(playlists):
        removed = playlists.pop(index)
        save_playlists(playlists)
        return removed
    return None


def shuffle_tracks(tracks: List[Track]) -> List[Track]:
    """Return a randomly shuffled copy of track list."""
    shuffled = list(tracks)
    random.shuffle(shuffled)
    return shuffled
