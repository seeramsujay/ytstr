"""
Configuration, constant paths, and terminal styling parameters for ytstr.
"""
import os
import platform
from pathlib import Path

# Ensure standard package manager binary directories are on PATH (especially on macOS)
for _bin_path in ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", os.path.expanduser("~/.local/bin")]:
    if os.path.isdir(_bin_path) and _bin_path not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = f"{_bin_path}{os.pathsep}{os.environ.get('PATH', '')}"

# Application Metadata
APP_NAME = "ytstr"
VERSION = "2.1.0"

# Directories & Files
CONFIG_DIR = Path(os.path.expanduser("~/.config/ytstr"))
PLAYLIST_FILE = CONFIG_DIR / "playlists"
YTM_AUTH_FILE = CONFIG_DIR / "ytm_auth.json"

# Cache Directory (Disk-backed, avoid filling RAM via /dev/shm)
CACHE_BASE_DIR = Path(os.path.expanduser("~/.cache/ytstr"))

# Audio DSP Defaults
DEFAULT_CROSSFADE_SEC = 3.0
ANALYSIS_WINDOW_MS = 5000
CHUNK_DURATION_SEC = 30.0
MAX_BUFFER_AHEAD_SEC = 25.0
MAX_PREFETCH_TRACKS = 2  # Strict boundary on forward prefetch to bound disk/memory

# Hysteresis Streaming Thresholds
STREAM_CHUNK_SEC: float = 6.0
LOW_WATERMARK_SEC: float = 8.0
HIGH_WATERMARK_SEC: float = 22.0

# ANSI Terminal Colors
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"


def global_media_keys_enabled() -> bool:
    """
    Whether hardware media-key interception via pynput is safe to enable.

    pynput's global keyboard listener is only reliable on Linux. On macOS the
    media keys are reserved by the system "Now Playing" center and creating a
    pynput listener aborts the process, so it is disabled by default.
    Override explicitly with YTSTR_MEDIA_KEYS=1 (enable) or =0 (disable).
    """
    override = os.environ.get("YTSTR_MEDIA_KEYS", "").strip().lower()
    if override in ("1", "true", "yes", "on"):
        return True
    if override in ("0", "false", "no", "off"):
        return False
    return platform.system() == "Linux"


def ensure_config_dir() -> Path:
    """Ensure configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not PLAYLIST_FILE.exists():
        PLAYLIST_FILE.touch()
    return CONFIG_DIR


def ensure_cache_dir() -> Path:
    """Ensure disk cache base directory exists."""
    CACHE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_BASE_DIR
