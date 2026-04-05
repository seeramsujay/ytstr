# 🎧 ytstr v2.0.0 — Intelligent Auto-DJ Streamer

> **Wired for Performance. Tuned for Perfection.**  
> A terminal-native YouTube playlist streamer powered by a psychoacoustic DecisionEngine for seamless, broadcast-grade transitions.

---

## 🚀 Why ytstr?
Most terminal streamers are just simple wrappers for MPV. **ytstr** is a high-fidelity playback engine that analyzes the energy, frequency, and dynamics of your music in real-time to select the perfect DJ transition between every track.

- **8 Specialized Transitions:** Rise, Melt, Tape Stop, Bass Swap, and more.
- **70% RAM Reduction:** Active backpressure and garbage collection stay under ~260MB even on long playlists.
- **System Native:** Global hardware media key support (F7-F9) and a clean, responsive TUI.

---

## ⚡ Quick Start

### 1. System Requirements
```bash
sudo apt update && sudo apt install mpv ffmpeg
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Global Installation (Recommended)
Integrate `ytstr` into your system `$PATH` to launch it from any directory:
```bash
ln -s $(realpath ytstr) ~/.local/bin/ytstr
```
*Now you can simply run `ytstr` from any terminal!*

---

## 🎨 Choose Your Mix

| Mode | Command | Impact | Best For |
|------|---------|--------|----------|
| **Auto-DJ** | `default` | High | The full DJ experience. |
| **Light Mix** | `--light-mix` | Med | Simple equal-power crossfading. |
| **No Mix** | `--no-mix` | Low | Pure sequential playback. |

---

## 🎹 Control Center

### Terminal Hotkeys
| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `>` | Next Track |
| `<` | Previous Track |
| `9` / `0` | Volume Down / Up |
| `q` | Skip to Next Track |
| `Shift + Q`| Quit Gracefully |

### 🌏 Global Media Keys
`ytstr` binds to your hardware media keys:
- **F7:** Previous Track | **F8:** Play/Pause | **F9:** Next Track

---

## 📂 Playlist Management
```bash
# Add a playlist
ytstr --add "Lofi Mix" "https://..."

# List saved playlists
ytstr --list

# Launch a saved playlist
ytstr 1
```

---

## 🚀 Performance & Stability (v2.0.0 Optimized)

| Mode | CPU (Peak) | Memory (RSS) | RAM Disk (SHM) |
|------|------------|--------------|----------------|
| **Auto-DJ** | ~100% | ~480 MB | **~260 MB** |
| **Light-Mix** | ~75% | ~510 MB | **210 MB** |
| **No-Mix** | ~40% | ~270 MB | **290 MB** |

> [!NOTE]
> **V2.0.0 Update:** RAM disk usage is now strictly bounded to ~3 track segments. The system automatically nukes old bake files as they finish playing.

---

## 📜 License
Licensed under the [GNU General Public License v3.0](LICENSE).
