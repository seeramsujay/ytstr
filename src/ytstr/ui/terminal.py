"""
Terminal UI formatting, badges, and playing banners.
"""
import sys
from ytstr.config import BOLD, CYAN, DIM, GREEN, MAGENTA, NC, RED, YELLOW
from ytstr.core.types import PlaybackMode, Track


def info(msg: str):
    print(f"{CYAN}{msg}{NC}")


def success(msg: str):
    print(f"{GREEN}{msg}{NC}")


def warn(msg: str):
    print(f"{YELLOW}{msg}{NC}")


def error(msg: str):
    print(f"{RED}Error: {msg}{NC}", file=sys.stderr)


def print_banner(version: str, mode: PlaybackMode, save_dir: str = ""):
    """Print launch banner with current mode and keyboard controls."""
    mode_str = ""
    if mode == PlaybackMode.NO_MIX:
        mode_str = f"{RED}OFF (--no-mix, ultra-low RAM direct playback){NC}"
    elif mode == PlaybackMode.STREAM:
        mode_str = f"{CYAN}Direct Stream (--stream, zero disk writes){NC}"
    elif mode == PlaybackMode.LIGHT_MIX:
        mode_str = f"{YELLOW}Light Mix (equal-power crossfade, low CPU){NC}"
    else:
        mode_str = f"{GREEN}Auto-DJ (DecisionEngine + 8 spectral transitions){NC}"

    print(f"\n{BOLD}ytstr v{version}{NC} — YouTube Audio Streamer")
    print(f"{CYAN}Mix Mode:{NC} {mode_str}")
    if save_dir:
        print(f"{MAGENTA}Save Destination:{NC} {save_dir}")
    print(
        f"{YELLOW}Controls: Space=pause, 9/0=volume, >/n=next, </p=prev, q=quit{NC}\n"
    )


def print_track_card(
    index: int, total: int, track: Track, next_track: Track = None, transition: str = ""
):
    """Print standard playing track banner."""
    print(f"\n{CYAN}━━━━━━━━━━━━━━━━━━━━ PLAYING ━━━━━━━━━━━━━━━━━━━━{NC}")
    print(f"{GREEN}[{index + 1}/{total}]{NC} {YELLOW}{track.display_title()}{NC}")
    if transition:
        print(f"{DIM}  ⚡ Transition: {transition}{NC}")
    if next_track:
        print(f"{DIM}  ↳ Next: {next_track.display_title()}{NC}")
    print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{NC}")
