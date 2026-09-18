# 🎧 ytstr: High-Speed CLI & GUI YouTube Music Streamer with Automatic Spectral-DJ Transitions

`ytstr` is a high-performance terminal and desktop YouTube / YouTube Music audio streamer equipped with an intelligent, automated DJ transition engine, an ultra-low-RAM direct streaming pipeline (< 30 MB peak RAM), and an InnerTune/Metrolist-inspired lightweight GUI.

---

## ⚡ Key Capabilities & Features

- **Ultra-Low Memory Footprint**:
  - **`--no-mix` Mode**: Bypasses in-memory Python DSP pipelines completely. Plays tracks directly via native `mpv` gapless queues with **< 30 MB RSS** (down from 114 MB, a 74% reduction).
  - **`--stream` Mode**: Streams audio URLs directly over HTTPS with **zero disk writes** and **< 30 MB RSS**.
  - **Bounded Cache & `--save`**: Replaced `/dev/shm` RAM disk exhaustion with an on-disk sliding-window cache (`~/.cache/ytstr`). Automatically unlinks played tracks or exports them file-by-file with `--save [DIR]`.
- **Intelligent Spectral Auto-DJ**:
  - Extracts acoustic features (RMS energy, sub-250 Hz kick/bass, treble above 2 kHz, and amplitude variance) across 5-second handoff windows to dynamically choose and render custom transitions:
    - **Bass Swap**: Exponential high-pass filter sweep with sub-120 Hz incoming kill to eliminate low-end collisions.
    - **Filter Wash**: Progressive high-pass filter sweep up to 2 kHz with 1–2 kHz resonance masking.
    - **Dynamic Rise**: Sinusoidal equal-power crossfade paired with an active +4 dB drop gain swell.
    - **Tape Stop / Start**: Progressive turntable frame-rate drop simulation.
    - **Melt**: Multi-tap echo delay lines with 3 kHz low-pass atmospheric dissolve.
    - **Blend**: 10-second groove lock for compatible tempos.
    - **Cut-In**: Beat-boundary switch with 15 ms anti-pop micro-fades.
    - **Fade**: Classic sinusoidal equal-power crossfade.
- **Lightweight YouTube Music Desktop GUI (`ytstr-gui`)**:
  - Built with native `tkinter` for an ultra-lean footprint (< 35 MB RAM) — zero Electron or Qt bloat.
  - Dark obsidian palette inspired by **InnerTune** and **Metrolist**.
  - Browse YouTube Music "Listen Again", "Quick Picks", "Trending & Charts", and "Moods & Genres".
  - One-click account authentication (browser cookie import or OAuth).
  - Search songs, albums, and start instant radio playlists.
- **Single-Line Universal Installer**:
  - Managed 100% via `uv` with reproducible locks and instant setup.

---

## 📊 Memory Benchmarks (Peak RSS)

| Mode | Previous Architecture | **ytstr v2.1.0 (Optimized)** | RAM Reduction |
| :--- | :---: | :---: | :---: |
| **Direct No-Mix (`--no-mix`)** | 114.31 MB | **29.92 MB** | **-73.8%** |
| **Direct Stream (`--stream`)** | N/A | **29.65 MB** | **Ultra-Low** |
| **Light Mix (`--light-mix`)** | 110.96 MB | **30.10 MB** | **-72.9%** |
| **Auto-DJ (Spectral Transitions)** | 111.48 MB | **29.86 MB** | **-73.2%** |

---

## 🚀 Quick Start & Installation

### 1. One-Line Installer (Recommended)

Run the single-script installer:

```bash
curl -fsSL https://raw.githubusercontent.com/seeramsujay/ytstr/master/install.sh | bash
```

The script verifies system decoders (`mpv`, `ffmpeg`), installs `uv` if missing, sets up the virtual environment, and links standalone executables to `~/.local/bin/ytstr` and `~/.local/bin/ytstr-gui`.

### 2. Manual Installation with `uv`

```bash
# Clone the repository
git clone https://github.com/seeramsujay/ytstr.git
cd ytstr

# Ensure system decoders are installed
sudo apt install -y mpv ffmpeg   # Debian/Ubuntu
# or: sudo pacman -S mpv ffmpeg  # Arch Linux

# Install dependencies and sync virtual environment
uv sync --extra media-keys --extra dev

# Run directly
uv run ytstr --help
```

---

## 💻 Usage & CLI Options

```bash
# Stream by search query in Direct Low-RAM mode (ideal for weak PCs)
ytstr "synthwave chill mix" --no-mix

# Stream directly from network without saving files to disk
ytstr "lofi hip hop radio" --stream

# Auto-DJ mode with psychoacoustic spectral transitions
ytstr "https://www.youtube.com/playlist?list=PL4fGSI1pDJn5kI81J1fYWK5eZRl1zJ5kM"

# Fast equal-power crossfade (Light Mix)
ytstr "cyberpunk 2077 radio" --light-mix

# Save files file-by-file into ~/Music/ytstr while streaming
ytstr "chill hop essentials" --save ~/Music/ytstr

# Launch the lightweight YouTube Music desktop GUI
ytstr --gui
# or:
ytstr-gui
```

### CLI Reference

| Flag | Description |
| :--- | :--- |
| `target` | YouTube URL, search query, or saved playlist number. |
| `--no-mix` | Ultra-low RAM direct playback without mixing (< 30 MB RSS). |
| `--stream` | Direct network streaming without writing files to disk. |
| `--light-mix` | Fast sinusoidal crossfade skipping spectral analysis (low CPU). |
| `--save [DIR]` | Save downloaded tracks file-by-file to destination directory. |
| `--no-shuffle` | Play tracks in original sequential order. |
| `--gui` | Launch lightweight desktop YouTube Music interface. |
| `--list` | List all saved playlists. |
| `--add NAME URL` | Save a playlist with a friendly name. |
| `--remove NUM` | Remove a saved playlist by index. |

---

## 🖥️ YouTube Music GUI (`ytstr-gui`)

Inspired by **InnerTune** and **Metrolist**, the desktop GUI provides a clean, native interface for YouTube Music:

- **Home Feed**: Displays "Listen Again", "Quick Picks", and trending community playlists.
- **Charts & Trending**: Top tracks and music videos.
- **Search & Radio**: Search tracks, albums, and artists, or click "📻 Radio" for endless auto-recommendations.
- **Authentication**:
  - Click **Log In** in the top right.
  - Paste request headers from `music.youtube.com` (from browser DevTools F12 -> Network).
  - Unlocks personalized library, history, and liked songs.

---

## ⌨️ Interactive Keyboard Controls

During terminal playback:

| Key | Action |
| :---: | :--- |
| `Space` | Toggle Play / Pause |
| `>` or `q` | Skip to next track |
| `<` | Skip to previous track |
| `9` / `0` | Decrease / Increase volume (5% steps) |
| `Q` | Graceful quit and temporary cache cleanup |
| `Media Keys` | Global hardware Play/Pause, Next, Previous (via `pynput` / F7-F9) |

---

## 🧪 Testing

Run the full automated test suite with `uv`:

```bash
uv run pytest -v
```

Run memory profiling benchmarks:

```bash
bash test_mem.sh
```

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0**. See the [LICENSE](LICENSE) file for details.

---

## 🛡️ Licensing & Privacy Protection

Because this repository contains personal code, portfolios, or intellectual property, **strict privacy protections are in place**.

### ⚠️ Prohibitions on AI Training & Scraping
This repository is published for direct human viewing only. Automated data scraping, harvesting, and crawling are strictly prohibited under the author's personal copyright terms.

**By accessing this repository or its contents, you agree to the following terms:**
* **NO AI/LLM Ingestion:** Any ingestion of code, text, layouts, designs, or assets for training, validation, testing, or tuning of machine learning models, neural networks, or artificial intelligence systems (such as Large Language Models) is strictly prohibited.
* **NO Automated Data Scraping:** Any automated extraction, parsing, harvesting, or scraping of content by bots, crawlers, scripts, or spiders is prohibited.
* **Personal Use Only:** Human viewing for personal or educational review is permitted. No duplication, modification, adaptation, or commercial distribution of this work is allowed without express written permission.
