# ytstr

A fast, terminal-native YouTube playlist streamer with intelligent RAM caching and Spotify-style crossfade mixing.

`ytstr` streams YouTube playlists through the `yt_dlp` and `python-mpv` libraries, caching audio in `/dev/shm` (RAM) for instant playback. It completely bypasses terminal execution limits by controlling dual `libmpv` player instances directly in Python, seamlessly crossfading transitions between songs — just like Spotify's mix feature.

## Features

- **Crossfade Mixing** — Spotify-style fade-out/fade-in between songs with configurable overlap (default 5s)
- **RAM Caching** — Audio cached to `/dev/shm` for near-instant playback with automatic eviction
- **Smart Preloading** — Downloads the next 2 and previous 1 tracks around the current position
- **Leading Silence Removal** — Strips silent padding from the start of each track
- **Playlist Management** — Save, list, and remove playlists with friendly names
- **Shuffle by Default** — Randomized playback order, disable with `--no-shuffle`
- **Battery Saver Mode** — `--no-mix` disables all audio processing for low-power playback

## Prerequisites

This is a Python 3 based tool.

| Tool | Install |
|------|---------|
| Python Deps | `pip install yt-dlp python-mpv` |
| [mpv](https://mpv.io/) | `sudo apt install libmpv-dev mpv` |

## Installation

```bash
git clone https://github.com/seeramsujay/ytstr.git
cd ytstr
chmod +x ytstr
```

### Add to PATH

**System-wide:**
```bash
sudo cp ytstr /usr/local/bin/
```

**User-local:**
```bash
mkdir -p ~/.local/bin
cp ytstr ~/.local/bin/

# Add to your shell config if not already present:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## Usage

```bash
# Play a YouTube playlist URL directly
ytstr 'https://youtube.com/playlist?list=PLxxx'

# Interactive playlist selection from saved playlists
ytstr

# Play saved playlist #1
ytstr 1

# Play without crossfade (battery saver)
ytstr --no-mix 1

# Play in original order, no crossfade
ytstr --no-shuffle --no-mix 'https://youtube.com/playlist?list=PLxxx'
```

### Playlist Management

```bash
# Save a playlist
ytstr --add 'Lofi Beats' 'https://youtube.com/playlist?list=PLxxx'

# List saved playlists
ytstr --list

# Remove saved playlist #2
ytstr --remove 2
```

### Options

| Flag | Description |
|------|-------------|
| `--list` | List all saved playlists |
| `--add <name> <url>` | Save a playlist with a friendly name |
| `--remove <number>` | Remove a saved playlist by index |
| `--no-shuffle` | Play tracks in original playlist order |
| `--no-mix` | Disable crossfade mixing (saves CPU/battery) |
| `-h`, `--help` | Show help message |

### Playback Controls

| Key | Action |
|-----|--------|
| `Space` | Pause / Resume |
| `>` | Next song |
| `<` | Previous song |
| `9` / `0` | Volume down / up |
| `q` | Skip to next song |
| `Shift+Q` | Quit player |

## How It Works

```
┌─────────────┐     ┌──────────┐     ┌─────────┐
│   yt-dlp    │     │ /dev/shm │     │   mpv   │
│  (fetch +   │────▶│  (RAM    │────▶│ (audio  │
│  download)  │     │  cache)  │     │ player) │
└─────────────┘     └──────────┘     └─────────┘
       │                                   │
       │  Preloads next 2 +           Lua script
       │  previous 1 tracks          monitors
       │                          time-remaining
       ▼                               │
  Evicts old                     Triggers fade-out
  cache entries                  + starts next song
```

### Crossfade Pipeline

1. The Python `YtstrPlayer` orchestrates two distinct `python-mpv` `MPV` instances (`player_a` and `player_b`).
2. An event listener attached to the active player's `time-remaining` property monitors playback globally.
3. When remaining time ≤ 5 seconds, Python triggers a seamless fadeout filter on the active player and immediately starts the next track on the standby player with a fade-in filter.
4. Leading silence is stripped natively via `silenceremove` so the new track's audio starts instantly.
5. Both player decoders actively stream directly from the RAM cache simultaneously, achieving an authentic Spotify-like transition.

### Caching Strategy

- Cache directory: `/dev/shm/ytstr_<PID>` (RAM-backed tmpfs)
- Window: current track ± 1 previous + 2 next
- Eviction runs after each track completes
- Full cleanup on exit (EXIT/INT/TERM traps)
- Typical memory usage: ~12 MB for a 4-track window

## Configuration

Playlists are stored in `~/.config/ytstr/playlists` as pipe-delimited entries:

```
Lofi Beats|https://youtube.com/playlist?list=PLxxx
Workout Mix|https://youtube.com/playlist?list=PLyyy
```

## License

This project is open-source and available under the [MIT License](LICENSE).
