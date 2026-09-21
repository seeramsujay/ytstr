#!/usr/bin/env bash
# ==============================================================================
# Build Standalone Linux Executable for ytstr
# ==============================================================================
set -e

echo "→ Building standalone binary ./ytstr..."
uv run pyinstaller --onefile --name ytstr \
    --paths src \
    --collect-all ytmusicapi \
    --collect-all yt_dlp \
    --collect-all pynput \
    src/ytstr/__main__.py

cp --remove-destination dist/ytstr ./ytstr
chmod +x ./ytstr
echo "✓ Standalone binary generated at: $(pwd)/ytstr ($(du -h ./ytstr | cut -f1))"
