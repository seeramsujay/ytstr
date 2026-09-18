"""
Configuration, constant paths, and terminal styling parameters for ytstr.
"""
import os
from pathlib import Path

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
