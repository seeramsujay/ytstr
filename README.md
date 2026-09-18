# 🎧 ytstr: High-Speed CLI & Interactive TUI YouTube Music Streamer

`ytstr` is a high-performance terminal YouTube and YouTube Music audio streamer equipped with an intelligent, automated spectral DJ transition engine, an ultra-low-RAM streaming pipeline (< 30 MB peak RAM), and an interactive **curses-based Terminal User Interface (TUI)**.

---

## ⚡ Key Capabilities & Features

- **Interactive Terminal User Interface (TUI)**:
  - Built with Python's standard library `curses` (< 5 MB RAM, zero extra dependencies).
  - Browse YouTube Music personalized sections (**"Listen Again"**, **"From Your Library"**, **"Mixed For You"**).
  - Browse **"Charts & Trending"** songs and videos.
  - Interactive search with `/` hotkey and instantaneous playback.
  - Live ASCII audio progress bar, playback timer, and volume adjustment.
  - Radio generator: Press `r` on any track to auto-generate endless recommendations.
- **1-Click Browser Authentication (Zen, Chrome, Firefox, Brave, etc.)**:
  - Automatically imports your authenticated YouTube session cookies from local browser profiles.
  - Full support for **Zen Browser**, standard **Firefox**, **Chrome**, **Brave**, **LibreWolf**, **Edge**, and **Chromium**.
  - No manual DevTools inspection or password entry required.
- **Ultra-Low Memory Footprint**:
  - **`--no-mix` Mode**: Direct native `mpv` playback with **< 30 MB RSS** (a 74% reduction).
  - **`--stream` Mode**: Streams audio URLs directly over HTTPS with **zero disk writes** and **< 30 MB RSS**.
  - **Bounded Cache & `--save`**: Replaced `/dev/shm` RAM storage with an on-disk sliding-window cache (`~/.cache/ytstr`). Automatically cleans up played tracks or exports them file-by-file with `--save [DIR]`.
- **Intelligent Spectral Auto-DJ**:
  - Analyzes RMS energy, kick/bass (< 250 Hz), treble (> 2 kHz), and amplitude variance to dynamically render:
    - **Bass Swap**: Exponential high-pass filter sweep with sub-120 Hz incoming kill.
    - **Filter Wash**: Progressive high-pass filter sweep up to 2 kHz with resonance masking.
    - **Dynamic Rise**: Equal-power crossfade paired with an active +4 dB drop gain swell.
    - **Tape Stop / Start**: Progressive turntable frame-rate drop simulation.
    - **Melt**: Multi-tap echo delay lines with 3 kHz low-pass atmospheric dissolve.
    - **Blend**: 10-second groove lock for compatible tempos.
    - **Cut-In**: Beat-boundary switch with 15 ms anti-pop micro-fades.
    - **Fade**: Classic sinusoidal equal-power crossfade.

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

The script verifies system decoders (`mpv`, `ffmpeg`), installs `uv` if missing, builds the environment, and creates standalone executables at `~/.local/bin/ytstr` and `~/.local/bin/ytstr-tui`.

### 2. 1-Click Login (Zen, Firefox, Chrome, Brave)

To connect your YouTube Music account:

```bash
ytstr --login
# Or specify your browser directly:
ytstr --login zen
```

This extracts your session cookies automatically without asking for credentials or storing passwords.

---

## 🖥️ Interactive TUI Navigation

Launch the TUI:

```bash
ytstr
# or:
ytstr --tui
```

### Keybindings

| Key | Action |
| :---: | :--- |
| `1` - `5` / `Tab` | Switch tabs: **Home**, **Charts**, **Search**, **Saved**, **Login** |
| `↑` / `↓` or `k` / `j` | Navigate items in list |
| `PageUp` / `PageDown` | Scroll 10 items |
| `Enter` | Play selected track or playlist |
| `Space` | Toggle Pause / Resume |
| `n` / `p` | Skip to Next / Previous track |
| `+` / `-` | Volume up / down (5% steps) |
| `/` | Open Search bar |
| `r` | Start infinite Radio from selected track |
| `s` | Save selected track or playlist to `~/.config/ytstr/playlists` |
| `m` | Cycle Playback Mode (Direct Low-RAM → Light Mix → Stream → Auto-DJ) |
| `x` | Stop playback |
| `q` | Quit TUI |

---

## 💻 CLI Usage Options

```bash
# Stream by search query in Direct Low-RAM mode (ideal for weak desktops)
ytstr "synthwave chill mix" --no-mix

# Stream directly from network without saving files to disk
ytstr "lofi hip hop radio" --stream

# Auto-DJ mode with psychoacoustic spectral transitions
ytstr "https://www.youtube.com/playlist?list=PL4fGSI1pDJn5kI81J1fYWK5eZRl1zJ5kM"

# Fast equal-power crossfade (Light Mix)
ytstr "cyberpunk 2077 radio" --light-mix

# Save files file-by-file into ~/Music/ytstr while streaming
ytstr "chill hop essentials" --save ~/Music/ytstr

# List saved playlists
ytstr --list

# Add a saved playlist
ytstr --add "Focus Beats" "https://www.youtube.com/playlist?list=..."
```

### CLI Reference

| Flag | Description |
| :--- | :--- |
| `target` | YouTube URL, search query, or saved playlist number. |
| `--tui` | Launch interactive terminal user interface (default if no target given). |
| `--no-mix` | Ultra-low RAM direct playback without mixing (< 30 MB RSS). |
| `--stream` | Direct network streaming without writing files to disk. |
| `--light-mix` | Fast sinusoidal crossfade skipping spectral analysis (low CPU). |
| `--save [DIR]` | Save downloaded tracks file-by-file to destination directory. |
| `--no-shuffle` | Play tracks in original sequential order. |
| `--login [BROWSER]` | 1-click browser login (auto, zen, chrome, firefox, brave, etc.). |
| `--logout` | Clear saved YouTube Music credentials. |
| `--list` | List all saved playlists. |
| `--add NAME URL` | Save a playlist with a friendly name. |
| `--remove NUM` | Remove a saved playlist by index. |

---

## 🧪 Testing & Benchmarks

Run the automated test suite with `uv`:

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
