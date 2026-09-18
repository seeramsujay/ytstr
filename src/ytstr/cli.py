"""
Command-line interface and argument router for ytstr.
"""
import argparse
import os
import sys
from typing import Optional

from ytstr.config import GREEN, NC, VERSION, YELLOW
from ytstr.core.player import YtstrCoordinator
from ytstr.core.playlist import add_playlist, parse_playlists, remove_playlist
from ytstr.core.types import PlaybackMode
from ytstr.ui.terminal import error, info, success, warn
from ytstr.ytm.auth import AuthManager


def main(argv: Optional[list] = None) -> int:
    """CLI entry point for ytstr."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="ytstr",
        description=f"ytstr v{VERSION} — YouTube & YT Music Streamer with Auto-DJ, Low-RAM Streaming & Interactive TUI",
        add_help=False,
    )

    # Actions
    parser.add_argument("--list", action="store_true", help="List all saved playlists")
    parser.add_argument("--add", nargs=2, metavar=("NAME", "URL"), help="Save a playlist with a friendly name")
    parser.add_argument("--remove", type=int, metavar="NUM", help="Remove a saved playlist by index")
    parser.add_argument("--tui", action="store_true", help="Launch interactive terminal user interface")
    parser.add_argument("--gui", action="store_true", help="Alias for --tui (interactive terminal interface)")
    parser.add_argument(
        "--login",
        nargs="?",
        const="auto",
        metavar="BROWSER",
        help="Log in to YouTube Music via browser (auto, zen, chrome, firefox, brave, edge, etc.)",
    )
    parser.add_argument("--logout", action="store_true", help="Log out of YouTube Music and clear credentials")

    # Playback Modes
    parser.add_argument("--no-shuffle", action="store_true", help="Play tracks in original sequential order")
    parser.add_argument("--no-mix", action="store_true", help="Ultra-low RAM direct playback without mixing")
    parser.add_argument("--light-mix", action="store_true", help="Fast equal-power crossfade (low CPU)")
    parser.add_argument("--stream", action="store_true", help="Direct network streaming without downloading files")
    parser.add_argument(
        "--save",
        nargs="?",
        const=os.path.expanduser("~/Music/ytstr"),
        metavar="DIR",
        help="Save audio files file-by-file to destination directory",
    )
    parser.add_argument("--ipc-socket", metavar="PATH", help="Path to mpv Unix IPC domain socket")
    parser.add_argument("-h", "--help", action="store_true", help="Show this help message and exit")
    parser.add_argument("-v", "--version", action="store_true", help="Show version number and exit")

    # Positional target
    parser.add_argument("target", nargs="?", help="YouTube URL, search query, or saved playlist number")

    args = parser.parse_args(argv)

    if args.version:
        print(f"ytstr v{VERSION}")
        return 0

    if args.help:
        parser.print_help()
        return 0

    auth_mgr = AuthManager()

    if args.logout:
        auth_mgr.logout()
        success("Logged out. YouTube Music credentials removed.")
        return 0

    if args.login:
        browser_choice = args.login
        info(f"Connecting to YouTube Music via browser ({browser_choice})...")
        auth_mgr.open_browser_for_login()
        info("Default browser opened to https://music.youtube.com. Attempting session extraction...")
        ok, msg = auth_mgr.import_cookies_from_browser(browser_choice)
        if ok:
            success(f"✓ {msg}")
            return 0
        else:
            warn(f"Note: {msg}")
            info("Make sure you are logged into YouTube in your browser, then re-run: ytstr --login")
            return 1

    if args.tui or args.gui or (not args.target and not args.list and not args.add and not args.remove):
        try:
            from ytstr.ui.tui import main as run_tui
            run_tui()
            return 0
        except Exception as e:
            error(f"Failed to launch TUI: {e}")
            return 1

    playlists = parse_playlists()

    if args.list:
        if not playlists:
            info("No saved playlists found. Add one with: ytstr --add <name> <url>")
            return 0
        info("Saved Playlists:")
        for i, p in enumerate(playlists):
            print(f"  {GREEN}{i + 1}.{NC} {p['name']} ({p['url']})")
        return 0

    if args.add:
        name, url = args.add
        if add_playlist(name, url):
            success(f"Added playlist: '{name}' -> {url}")
            return 0
        else:
            error("Failed to add playlist.")
            return 1

    if args.remove is not None:
        idx = args.remove - 1
        if 0 <= idx < len(playlists):
            removed = playlists[idx]
            if remove_playlist(idx):
                success(f"Removed playlist: '{removed['name']}'")
                return 0
        error(f"Invalid playlist number: {args.remove}")
        return 1

    # Playback mode determination
    if args.stream:
        mode = PlaybackMode.STREAM
    elif args.no_mix:
        mode = PlaybackMode.NO_MIX
    elif args.light_mix:
        mode = PlaybackMode.LIGHT_MIX
    else:
        mode = PlaybackMode.AUTO_DJ

    shuffle = not args.no_shuffle

    # Resolve target: URL, saved playlist number, or search query
    target = args.target
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(playlists):
            target = playlists[idx]["url"]
            info(f"Using saved playlist #{idx + 1}: {playlists[idx]['name']}")
        else:
            error(f"Saved playlist #{target} does not exist.")
            return 1

    coordinator = YtstrCoordinator(
        target=target,
        mode=mode,
        shuffle=shuffle,
        save_dir=args.save,
    )
    if args.ipc_socket:
        coordinator.cache_mgr.ipc_socket = args.ipc_socket

    return coordinator.run()
