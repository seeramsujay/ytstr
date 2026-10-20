"""
Main entry point when executing `python -m ytstr`.
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--ytstr-ytdlp-worker":
        # Frozen builds re-invoke themselves as the yt-dlp CLI (see downloader.ytdlp)
        from ytstr.downloader.ytdlp import run_ytdlp_worker

        sys.exit(run_ytdlp_worker(sys.argv[2:]))

    from ytstr.cli import main

    sys.exit(main())
