# 🎧 ytstr v4.1.0 — Intelligent Auto-DJ Streamer

> **Wired for Performance. Tuned for Perfection.**  
> A terminal-native YouTube playlist streamer powered by a psychoacoustic DecisionEngine for seamless, broadcast-grade transitions.

---

## ⚡ Quick Start

### 1. System Requirements
Ensure you have the core media handlers installed on your system:
```bash
sudo apt update && sudo apt install mpv ffmpeg
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Launch the Music
Stream any YouTube playlist or video immediately:
```bash
./ytstr "https://www.youtube.com/playlist?list=..."
```

---

## 🎨 Choose Your Mix

| Mode | Command | Impact | Best For |
|------|---------|--------|----------|
| **Auto-DJ** | `default` | High | The full DJ experience with 8 transition styles. |
| **Light Mix** | `--light-mix` | Med | Simple equal-power crossfading. Lower CPU. |
| **No Mix** | `--no-mix` | Low | Pure sequential playback. Battery saver. |

---

## 🎹 Control Your Sound

### Terminal Hotkeys
| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `>` | Next Track |
| `<` | Previous Track |
| `9` / `0` | Volume Down / Up |
| `q` | Skip to Next Track |
| `Shift + Q`| Quit Gracefully |

### 🌍 Global Media Keys (Hardware)
`ytstr` automatically binds to your system's hardware media keys:
- **F7:** Previous Track
- **F8:** Play / Pause
- **F9:** Next Track

---

## 🎭 The 8 DJ Transition Styles
The **DecisionEngine** analyzes the spectral energy (Bass/Treble/RMS) of every track pair to select the perfect transition:

1.  **Fade:** Classic sinusoidal crossfade.
2.  **Blend:** Long, overlapping crossover for steady grooves.
3.  **Rise:** Energy-matched surge for incoming drops.
4.  **Cut In:** Immediate transition for high-impact starts.
5.  **Bass Swap:** Swaps low-end frequencies to prevent "muddy" overlaps.
6.  **Filter Wash:** Sweeps out the treble for a clean exit.
7.  **Melt:** Dissolves the outgoing track into the next.
8.  **Tape Stop:** A signature DJ "spin-down" effect for clashing tracks.

---

## 📂 Playlist Management
Save your favorite playlists with friendly names for instant access:

- **Add:** `./ytstr --add "Lofi Mix" "https://..."`
- **List:** `./ytstr --list`
- **Remove:** `./ytstr --remove 3`
- **Launch Saved:** `./ytstr 1` (Plays the first saved playlist)

---

## 🚀 Performance & Stability (V4.1.0 Optimized)

The engine is built on a high-stability daemon architecture with active **Backpressure** and **Garbage Collection**.

| Mode | CPU (Peak) | Memory (RSS) | RAM Disk (SHM) |
|------|------------|--------------|----------------|
| **Auto-DJ** | ~100% | ~480 MB | **~260 MB** |
| **Light-Mix** | ~75% | ~510 MB | **~210 MB** |
| **No-Mix** | ~40% | ~270 MB | **~290 MB** |

> [!NOTE]
> **V4.1.0 Update:** RAM disk usage is now strictly bounded to ~3 track segments. The system automatically nukes old bake files as they finish playing, reducing memory footprint by **70%**.

---

## 📜 License
This project is free software: you can redistribute it and/or modify it under the terms of the **GNU General Public License v3.0** as published by the Free Software Foundation. 

See the [LICENSE](LICENSE) file for the full text.
