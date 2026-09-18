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
        description=f"ytstr v{VERSION} — YouTube & YT Music Streamer with Auto-DJ and Low-RAM Streaming",
        add_help=False,
    )

    # Actions
    parser.add_argument("--list", action="store_true", help="List all saved playlists")
    parser.add_argument("--add", nargs=2, metavar=("NAME", "URL"), help="Save a playlist with a friendly name")
    parser.add_argument("--remove", type=int, metavar="NUM", help="Remove a saved playlist by index")
    parser.add_argument("--gui", action="store_true", help="Launch lightweight YouTube Music desktop GUI")
    parser.add_argument(
        "--login",
        nargs="?",
        const="auto",
        metavar="BROWSER",
        help="Log in to YouTube Music via browser (auto, chrome, firefox, brave, edge, etc.)",
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

    if args.gui:
        try:
            from ytstr.ytm.gui import main as run_gui
            run_gui()
            return 0
        except Exception as e:
            error(f"Failed to launch GUI: {e}")
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
            success(f"Added playlist: '{name}'")
            return 0
        error("Failed to add playlist.")
        return 1

    if args.remove is not None:
        idx = args.remove - 1
        removed = remove_playlist(idx)
        if removed:
            success(f"Removed playlist: '{removed['name']}'")
            return 0
        error(f"Invalid playlist number: {args.remove}")
        return 1

    target = args.target

    if not target:
        if not playlists:
            info("Usage: ytstr <search-query-or-url> [options]")
            info("Or run: ytstr --gui to browse YouTube Music")
            return 0

        info("Select a saved playlist:")
        for i, p in enumerate(playlists):
            print(f"  {GREEN}{i + 1}.{NC} {p['name']}")

        try:
            choice = input(f"\n{YELLOW}Enter playlist number:{NC} ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(playlists):
                target = playlists[idx]["url"]
            else:
                error("Invalid selection.")
                return 1
        except (ValueError, KeyboardInterrupt, EOFError):
            return 0

    # Resolve numerical shortcut
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(playlists):
            target = playlists[idx]["url"]
        else:
            error(f"Playlist index {target} not found in saved list.")
            return 1

    # Determine playback mode
    mode = PlaybackMode.AUTO_DJ
    if args.stream:
        mode = PlaybackMode.STREAM
    elif args.no_mix:
        mode = PlaybackMode.NO_MIX
    elif args.light_mix:
        mode = PlaybackMode.LIGHT_MIX

    coordinator = YtstrCoordinator(
        target=target,
        mode=mode,
        shuffle=not args.no_shuffle,
        save_dir=args.save,
    )
    coordinator.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
