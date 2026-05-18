#!/bin/bash
# Download a couple of songs via yt-dlp first
yt-dlp -x --audio-format opus -o "/tmp/song1.opus" "https://www.youtube.com/watch?v=BaW_jenozKc"
yt-dlp -x --audio-format opus -o "/tmp/song2.opus" "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
