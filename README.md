# 🎧 Ytstr: High-Speed CLI YouTube Streamer with Automatic Spectral-DJ Transitions

Ytstr is an advanced, terminal-first YouTube audio streamer equipped with an intelligent, automated DJ transition engine. It performs real-time spectral-energy analysis on track handoffs to dynamically apply custom DJ transitions (crossfades, filter sweeps, bass-line swaps, reverb melts, and turntable tape-stops) — delivering a gapless, radio-like listening experience within a microscopic system footprint.

---

## 🏗️ System Architecture & Transition Flow

Ytstr bridges stream ingestion and playback by running offline DSP transformations on overlapping track boundaries:

```
    [ YouTube Search / Query ] ──► (yt-dlp URL Ingestion)
                 │
                 ▼
     [ High-Speed Temp Cache ] ──► (ffmpeg Chunk Demuxing)
                 │
                 ▼
      [ Spectral-Energy Engine ] ──► (RMS, Bass, Treble, Variance Analysis)
                 │
                 ▼
       [ DJ Decision Engine ] ──► (Selects Best Transition Rule)
                 │
                 ▼
   [ pydub DSP Transition Mixer ] ──► (Renders Crossfade/Warp/Filter)
                 │
                 ▼
      [ mpv Playback Engine ] ──► (IPC Unix Socket Control Loop)
```

---

## ⚡ Key Persuasion Points & Features

- **Intelligent Handoff Analysis**: Extracts audio characteristics (signal RMS, kick-drum sub-250 Hz energy, treble above 2 kHz, and amplitude variance) from the ending and starting 5-second track windows to determine the optimal transition.
- **Premium DSP Transition Palette**:
  - **Bass Swap**: Sweeps a high-pass filter exponentially on the outgoing track while enforcing a "full kill" sub-120 Hz HP on the incoming track to prevent muddy low-end collisions.
  - **Filter Wash**: Sweeps high-pass cutoffs up to 2 kHz, blending a progress resonance bandpass to mask clashing harmonic keys.
  - **Melt**: Multi-tap echo delay lines attenuated over an extended 4-second decay window, dissolved using a 3 kHz low-pass filter.
  - **Tape Stop / Start**: Adjusts raw audio frame rates progressively to simulate vinyl turntables grinding to a halt or spinning up.
  - **Dynamic Rise**: Sinusoidal equal-power crossfade paired with an active +4 dB gain swell on the incoming drop.
- **Low-Resource IPC Orchestration**: Controls `mpv` via Unix sockets, consuming a microscopic fraction of the RAM used by browser-based players.
- **Full Interactive TTY Controls**: Pause, skip, seek, and toggle volume in the terminal. Includes hardware media-key hook options via `pynput`.

---

## 🛠️ Environmental Constraints & Protocol Alignment

Aligned with the sovereign **ANTIGRAVITY Protocol**, Ytstr is optimized for high-bandwidth execution:
- **Zero Heavy ML**: All audio characteristics are calculated using raw RMS and math-based frequency estimators inside `pydub`, completely avoiding heavy local ML frameworks.
- **System Offloading**: Offloads rendering and playback processes to standard system packages (`mpv`, `ffmpeg`), ensuring smooth execution on dual-core setups (Mac Air 2017 i5, 8GB RAM).

---

## 🚀 Quick Start (60-Second Onboarding)

### 1. Install System Requirements
Install the core media decoders:
```bash
sudo apt install mpv ffmpeg
```

### 2. Install Python Packages
```bash
pip install yt-dlp pydub pynput
```

### 3. Stream from the Terminal
Start streaming a direct URL or keyword query:
```bash
# Stream by search query (Auto-mix mode)
./ytstr "cyberpunk synthwave mix"

# Stream with sequential playback (No-mix low-compute mode)
./ytstr "lofi hip hop radio" --no-mix
```

---

## 📄 License
This project is licensed under the GPL-3.0 License. See the `LICENSE` file for details.
