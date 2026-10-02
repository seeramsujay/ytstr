#!/usr/bin/env bash
# ==============================================================================
# Build Standalone Executable for ytstr (Linux ELF & macOS Mach-O)
# ==============================================================================
set -e

echo "→ Building standalone binary ./ytstr..."
uv run pyinstaller --onefile --name ytstr \
    --paths src \
    --collect-all ytmusicapi \
    --collect-all yt_dlp \
    --collect-all pynput \
    src/ytstr/__main__.py

rm -f ./ytstr
cp dist/ytstr ./ytstr
chmod +x ./ytstr
echo "✓ Standalone binary generated at: $(pwd)/ytstr ($(du -h ./ytstr | cut -f1))"
