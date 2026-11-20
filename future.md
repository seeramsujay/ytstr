# 🔮 Future Horizons & Strategic Roadmap: ytstr

> Production engineering roadmap for ultra-low memory YouTube & YouTube Music streaming, automated DJing, and terminal-native audio engines.

---

## 🎯 Executive Vision
`ytstr` is engineered for lightning-speed terminal music playback and seamless automated transitions while respecting strict hardware constraints (< 30 MB peak RSS). It transforms MPV into an autonomous, browser-authenticated personal streaming hub.

---

## 🚀 Architectural Evolutions & Innovations

### 1. High-Performance Audio Pipeline & DSP Engine
- **Hardware-Accelerated WebRTC / PipeWire Sink**: Direct ALSA/PipeWire kernel streaming to bypass high-level desktop sound daemon latency and audio resampling artifacts.
- **In-Memory Ring-Buffer Stream Decoupling**: Isolate raw FFmpeg / yt-dlp network chunks into bounded C-extension ring buffers to prevent audio stutter during intermittent WiFi packet drops.
- **BPM & Beatgrid Alignment Engine**: Supplement spectral frequency analysis with real-time onset detection and phase beatgrid matching for automated club-grade 32-beat phrase crossfades.

### 2. Autonomous DJ & Smart Discovery
- **Local Latent Acoustic Embeddings**: Use lightweight on-device audio feature extraction (chroma, MFCC, spectral centroid) to cluster liked songs by musical mood and key compatibility (Camelot wheel harmonizing).
- **Zero-Token Autonomous Radio**: Auto-generate endless track queues by synthesizing user listening telemetry with local Markov transition graphs.
- **Offline Ephemeral Caching**: Smart pre-caching of the next 2 queued tracks using LZ4-compressed temporary memory buffers, automatically truncated when playback ends.

### 3. Terminal Interface & Remote Control
- **Headless MPD / MPRIS Daemon Protocol**: Expose standard MPRIS2 and MPD (Music Player Daemon) interfaces allowing control from system media keys, polybar/waybar widgets, or mobile MPD clients.
- **Rich Terminal Spectrum Visualizer**: Native terminal braille/block FFT audio frequency waterfall visualizer operating at 60 FPS under < 2% CPU overhead.

---

## 📅 Phased Milestone Roadmap

| Horizon | Milestone | Core Deliverables | Target Objective |
|:---:|:---|:---|:---|
| **Phase 1** | Audio Engine Hardening | PipeWire sink integration, gapless buffer preload, and MPRIS2 DBus interface. | Zero-gap seamless playback. |
| **Phase 2** | Camelot Harmonic Mixing | Real-time key detection, BPM phase matching, and 8-band psychoacoustic EQ transitions. | Seamless automated DJing. |
| **Phase 3** | Headless MPD Daemon | Lightweight background daemon mode, mobile remote sync, and terminal braille visualizer. | Ubiquitous desktop integration. |

---
*Maintained and documented for high-fidelity audio engineering.*
