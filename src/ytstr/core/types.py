"""
Data models, enums, and types used across ytstr.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PlaybackMode(str, Enum):
    """Playback and mixing modes."""
    AUTO_DJ = "auto_dj"        # Spectral-energy auto transition engine
    LIGHT_MIX = "light_mix"    # Fast equal-power crossfade
    NO_MIX = "no_mix"          # Direct sequential playback (lowest RAM & CPU)
    STREAM = "stream"          # Zero-download direct streaming via mpv


class TransitionType(str, Enum):
    """Psychoacoustic DJ transition styles."""
    FADE = "fade"
    BLEND = "blend"
    CUT_IN = "cut_in"
    RISE = "rise"
    BASS_SWAP = "bass_swap"
    FILTER_WASH = "filter_wash"
    MELT = "melt"
    TAPE_STOP = "tape_stop"


@dataclass
class Track:
    """Represents a playable YouTube / YouTube Music track."""
    id: str
    title: str = "Unknown Title"
    artist: Optional[str] = None
    duration_sec: float = 0.0
    url: Optional[str] = None
    file_path: Optional[str] = None
    stream_url: Optional[str] = None
    thumbnail_url: Optional[str] = None

    @property
    def web_url(self) -> str:
        """Full web URL to the YouTube video."""
        if self.url:
            return self.url
        return f"https://www.youtube.com/watch?v={self.id}"

    def display_title(self) -> str:
        """User-friendly title with artist if present."""
        clean_title = self.title or "Unknown Title"
        if self.artist:
            return f"{self.artist} - {clean_title}"
        return clean_title


@dataclass
class DJTransitionResult:
    """Result of computing a transition between two audio segments."""
    transition_type: TransitionType
    effective_duration_ms: int
    rule_reason: str = ""
