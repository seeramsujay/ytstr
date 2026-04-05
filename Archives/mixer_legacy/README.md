<div align="center">

# 🎛️ mixer

**A terminal-native, psychoacoustically-grounded auto-DJ daemon.**

It loads your music folder, analyses every track pair with a spectral decision engine, picks the *correct* DJ transition, and streams a perfectly gapless mix to `mpv` — all in real time, with a microscopic ≈15 MB RAM footprint.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-yellow.svg)](https://python.org)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-lightgrey.svg)](https://kernel.org)

```
cd ~/Music && mixer
```

</div>

---

## Why this exists

Most "auto-crossfade" scripts are a `fade_out() + fade_in()` loop. That produces a 3 dB volume dip at every transition midpoint — the acoustic equivalent of your DJ falling asleep mid-mix.

Professional DJ software (Mixxx, Traktor, Serato) solves this but requires a GUI, high CPU, and manual operation. Broadcasting daemons (Liquidsoap, AzuraCast) require server infrastructure, config files, and a PhD.

**mixer fills the gap:** a single Python script, no config, no GUI, no server — just `cd` into your music folder and run it.

---

## How it works

```
Your Music Folder
      │
      ▼
┌─────────────────────────────────┐
│  1. File Discovery & Shuffle    │  find_all_audio_files()
└────────────────┬────────────────┘
                 │  Lazy pop(0) one at a time
                 ▼
┌─────────────────────────────────┐
│  2. Load & RMS Energy Trim      │  trim_to_energy()
│     Cuts dead-air intros/outros │  threshold = 50% of avg RMS
└────────────────┬────────────────┘
                 │  5-second analysis window
                 ▼
┌─────────────────────────────────┐
│  3. Decision Engine             │  DecisionEngine.select_transition()
│     Extracts: RMS, bass RMS,    │
│     treble RMS, energy variance │
│     → picks 1 of 8 transitions  │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  4. Transition Baking           │  process_track_pair()
│     Equal-power sinusoidal      │
│     fade curves (no 3 dB dip)   │
└────────────────┬────────────────┘
                 │  Written to /dev/shm/ (RAM disk)
                 ▼
┌─────────────────────────────────┐
│  5. mpv IPC Streaming           │  send_mpv_command()
│     loadfile … append-play      │
│     Gapless audio guaranteed    │
└─────────────────────────────────┘
```

Everything from step 2 onwards runs in a **background thread**, so baking never blocks playback. The main thread just polls mpv and feeds it the next pre-baked chunk when the buffer runs low.

---

## The 8 Transitions

The Decision Engine's priority waterfall selects the best technique for each pair:

| # | Transition | Trigger | What happens | Best for |
|---|-----------|---------|-------------|---------|
| 1 | **Rise** | Incoming track ≥ 1.8× louder than outgoing | Progressive 0→+4 dB energy swell on the incoming track | Drop moments, climactic chorus hits |
| 2 | **Bass Swap** | Both tracks > 40% sub-bass energy | Exponential HP sweep (80→800 Hz) on outgoing + 120 Hz HP kill on incoming | Back-to-back EDM, Hip-Hop, Drum & Bass |
| 3 | **Filter Wash** | Outgoing treble > 1.8× its bass | HP sweep (80→2 kHz) with a 1–2 kHz resonance bump fading in over the second half | Cluttered, treble-heavy outros |
| 4 | **Cut In** | Outgoing < 25% of incoming energy | Hard switch with a 15 ms anti-pop micro-fade | Genre jumps (e.g. 128 BPM House → 90 BPM Hip-Hop) |
| 5 | **Melt** | Outgoing has high energy variance | 3-tap multi-echo (200/400/700 ms, −3/−6/−10 dB) + 3 kHz low-pass dissolve | Psychedelic, Lo-Fi, Ambient |
| 6 | **Blend** | Both tracks have low energy variance | Extended 10 s equal-power overlap — lets grooves lock naturally | House, Techno, steady-pulse EDM |
| 7 | **Fade** | Default | Classic equal-power sinusoidal crossfade | Pop, Rock, Vocals |
| 8 | **Tape Stop** | Very different energy/dynamics profiles | Tape warp crossfade: outgoing winds DOWN while incoming warps UP | The "Universal Fallback" for clashing genres |

### Why equal-power and not linear?

A linear crossfade halves the amplitude of both signals at the midpoint. Because the signals are uncorrelated, their powers *add* — meaning you lose 3 dB of perceived energy right at the transition's peak. The equal-power (sine/cosine) curve ensures:

```
a²(t) + a²(1-t) = 1   for all t ∈ [0, 1]
```

The combined acoustic power stays perfectly flat throughout the mix. This is the same math used in professional consoles, DAWs, and the ITU-R BS.1770 loudness standard.

---

## Installation

### Dependencies

| Tool | Purpose | Install |
|------|---------|---------|
| `mpv` | Gapless audio playback daemon | `apt install mpv` / `brew install mpv` |
| `ffmpeg` | Audio format decoding (mp3, m4a, flac, …) | `apt install ffmpeg` / `brew install ffmpeg` |
| `pydub` | Python audio DSP library | `pip install pydub` |

```bash
# Ubuntu / Debian
sudo apt install mpv ffmpeg
pip install pydub

# macOS (Homebrew)
brew install mpv ffmpeg
pip install pydub
```

### Getting mixer

```bash
git clone https://github.com/seeramsujay/mixer
cd mixer
chmod +x mixer
```

### Optional: Add to PATH

```bash
# System-wide
sudo ln -s "$(pwd)/mixer" /usr/local/bin/mixer

# Or user-local
mkdir -p ~/.local/bin
ln -s "$(pwd)/mixer" ~/.local/bin/mixer
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

---

## Usage

```bash
cd /path/to/your/music
mixer
```

That's the entire interface. Press `Ctrl+C` to stop cleanly — mpv is sent a `quit` command and `/dev/shm` is garbage-collected.

### Supported formats

`mp3` · `m4a` · `wav` · `opus` · `flac` · `ogg` · `aac` · `webm`

Any format ffmpeg can decode will work.

### What gets played

Every audio file in the current directory (excluding `mixer_tmp*` and `mixer_part_*` chunks from the daemon itself). The playlist is **randomly shuffled** before playback.

---

## Performance Profile

| Metric | Value |
|--------|-------|
| RAM per chunk in `/dev/shm` | ~10–30 MB (stereo WAV at 44.1 kHz) |
| Max chunks in `/dev/shm` at once | 3 (current + next + 1 GC buffer) |
| mpv demuxer cache | 10 MB forward + 5 MB back |
| **Total peak RAM footprint** | **≈ 60–100 MB** |
| SSD writes | **Zero** (all staging via RAM disk) |

---

## Architecture

```
mixer (main process)
├── main()                          # Main loop — polls mpv, feeds chunks
│   ├── find_all_audio_files()      # Scans CWD for audio
│   ├── send_mpv_command()          # Unix socket IPC to mpv
│   └── cleanup_shm_parts()        # GC of /dev/shm/*.wav chunks
│
└── audio_processor_thread()        # Background worker
    ├── load_and_trim()             # Load + RMS energy trim
    ├── DecisionEngine
    │   ├── _analyze()              # Extract RMS, bass, treble, variance
    │   └── select_transition()     # Priority-waterfall rule engine
    └── process_track_pair()        # Bake chunk → export to /dev/shm
        └── apply_transition()      # Dispatch to transition handler
            ├── trans_fade()
            ├── trans_blend()
            ├── trans_rise()
            ├── trans_cut_in()
            ├── trans_bass_swap()
            ├── trans_filter_wash()
            ├── trans_melt()
            └── trans_tape_stop()
```

---

## Codebase

| File | Description |
|------|-------------|
| `mixer` | **V2 — Main script.** Intelligent auto-DJ with the Decision Engine and 8 transitions. |
| `lightMixer` | **V1 — Reference implementation.** Single equal-power crossfade for all pairs. Useful as a baseline or fallback if pydub filter calls break on non-standard sample rates. |
| `mix.py` | **V0 — Proof of concept.** Hard-coded 3 tracks, linear fade, no IPC. |
| `mix_spotify.py` | **V0b — Spotify-threshold variant.** Uses −45 dBFS silence detection instead of RMS energy. |

---

## Research Basis

The transition algorithms are grounded in academic DSP literature:

- **Equal-power crossfade math** — [Signal Processing Stack Exchange](https://dsp.stackexchange.com/questions/14754/equal-power-crossfade), ITU-R BS.1770
- **Psychoacoustic harmonic mixing** — Terhardt's sensory consonance model, ERB-scale masking (Parncutt / Moore & Glasberg)
- **Bass swap as a psychoacoustic requirement** — sub-bass constructive interference causes clipping and masking that cannot be corrected by volume alone
- **Filter sweep Q-factor / resonance** — the resonance artifact at the moving cutoff masks harmonic dissonance between clashing keys
- **Automated switch point detection** — STAT and EXPERT methodologies from MIR literature (Zenodo / ISMIR papers on EDM structural analysis)

Full citations available in [`Research_Report.md`](Research_Report.md).

---

## Roadmap

See [`roadmap.md`](roadmap.md) for the project history and [`Future_Steps.md`](Future_Steps.md) for planned features, including:

- **V2.1:** BPM-aware blend duration, harmonic key detection (Camelot Wheel), onset-snapped cut-in timing
- **V3:** Graph-based playlist reordering (Travelling Salesman over energy/key/BPM distance)
- **V4+:** REST control interface, real-time terminal visualiser, drop-in plugin system

---

## Contributing

Pull requests welcome. If you're adding a new transition style:

1. Write a `trans_yourname(current_song, next_song, fade_ms) -> (AudioSegment, int)` function.
2. Register it in the `TRANSITIONS` dict.
3. Add a rule to `DecisionEngine.select_transition()` with a clear psychoacoustic or energy-based trigger.
4. Document the trigger condition and perceptual effect in the docstring.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgements

Built on [pydub](https://github.com/jiaaro/pydub) by James Robert (jiaaro) and the incredible [mpv](https://mpv.io) media player.
