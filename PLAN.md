# Implementation Plan: ytstr Overhaul — Memory Optimization, Modular Refactoring, YouTube Music GUI, & uv Tooling

## 1. Executive Summary & Goals

The goal of this overhaul is to transform `ytstr` from a single-file monolithic CLI script into a production-grade, highly optimized audio streaming platform. Specifically:
- **Rectify all RAM issues**: Eliminate RAM-disk (`/dev/shm`) exhaustion, implement bounded disk caching with sliding-window LRU cleanup, optimize audio buffer allocation, and provide `--save` (file-by-file export) and `--stream` (direct streaming) options.
- **Fix `--no-mix` mode**: Build a dedicated zero-Python-DSP direct playback engine that passes files/streams directly to `mpv`, reducing RAM usage to a fraction (<25 MB RSS) on low-spec desktops.
- **Segregate and refactor codebase**: Decompose `ytstr` into clear, heavily documented, and type-annotated modules under a proper package structure.
- **YouTube Music integration & Light GUI**: Build a native, ultra-lightweight dark-mode GUI (InnerTune / Metrolist style) powered by `ytmusicapi` for YouTube Music authentication, personalized homepage browsing, recommendations, and one-click playback.
- **Modern packaging & single-line installer**: Standardize on `uv` (`pyproject.toml`, `uv.lock`), provide comprehensive `pytest` test suites, and write a one-line `curl ... | bash` `install.sh`.
- **Staged Git commits**: Execute and commit each milestone incrementally.

---

## 2. Root-Cause Analysis of Memory Inefficiencies

| Component | Current Defect | Impact | Rectified Solution |
| :--- | :--- | :--- | :--- |
| **Storage Cache** | Stores all downloaded `.opus` files in `/dev/shm` (RAM tmpfs) | Consumes 50–500 MB of physical RAM; crashes low-spec machines on long playlists | Shift to disk cache (`~/.cache/ytstr` or temp disk); implement sliding-window prefetch (prune played tracks unless `--save` is set) |
| **`--no-mix` Mode** | Still decodes 40s chunks via `ffmpeg` to uncompressed 44.1kHz stereo PCM in Python `AudioSegment` and writes to stdin | Uses 114+ MB RAM and causes high CPU thrashing even with `--no-mix` | Dedicated `DirectPlayer` bypassing Python audio buffers entirely; mpv plays audio files/streams directly gaplessly |
| **Audio Splicing / Buffer** | 40-second uncompressed WAVs held in Python memory | Holds ~7 MB raw PCM per chunk in Python heap with delayed GC | Keep chunk windows tight, only decode transition windows (5s overlap) into Python memory; stream the bulk of tracks via lightweight I/O |
| **Prefetch Unbounded** | `download_worker` prefetches tracks without boundary checks on disk size | Accumulates files indefinitely during playback | Strict 2-track forward prefetch window with configurable max cache size and automatic LRU eviction |

---

## 3. Architecture & Code Segregation Plan

```
ytstr/
├── pyproject.toml              # Modern uv-managed project configuration
├── install.sh                  # One-line installer script
├── ytstr                       # Backward-compatible CLI launcher script
├── src/
│   └── ytstr/
│       ├── __init__.py         # Package metadata & version
│       ├── __main__.py         # Module execution entrypoint (`uv run python -m ytstr`)
│       ├── cli.py              # CLI parser, arguments, subcommand router
│       ├── config.py           # Paths, cache thresholds, default configurations
│       ├── core/
│       │   ├── __init__.py
│       │   ├── types.py        # Track, Playlist, TransitionType, PlaybackState dataclasses
│       │   ├── playlist.py     # Playlist parsing, file persistence, shuffle logic
│       │   └── player.py       # Player coordinator connecting engines to UI
│       ├── audio/
│       │   ├── __init__.py
│       │   ├── dsp.py          # Equal-power curves, energy trim, progressive filters, tape stop/start
│       │   ├── transitions.py  # 8 transition algorithms (fade, blend, rise, bass_swap, filter_wash, melt, tape_stop, cut_in)
│       │   └── engine.py       # DecisionEngine (5s spectral energy, RMS, bass, treble, variance analysis)
│       ├── playback/
│       │   ├── __init__.py
│       │   ├── mpv_ipc.py      # Robust MPV Unix IPC socket client & process lifecycle
│       │   ├── direct.py       # Ultra-low RAM direct mpv playlist/stream player (--no-mix)
│       │   └── mixed.py        # Streaming chunk mixer & transition orchestrator
│       ├── downloader/
│       │   ├── __init__.py
│       │   ├── ytdlp.py        # yt-dlp wrapper for stream URLs and bounded audio downloads
│       │   └── cache.py        # Disk cache manager with sliding-window LRU & file-by-file export
│       ├── ytm/
│       │   ├── __init__.py
│       │   ├── client.py       # ytmusicapi client (homepage, recommendations, playlists, search)
│       │   ├── auth.py         # OAuth / browser cookie authentication manager
│       │   └── gui.py          # Lightweight Tkinter modern dark GUI (InnerTune / Metrolist style)
│       └── ui/
│           ├── __init__.py
│           ├── terminal.py     # Formatted terminal UI, status badges, playback progress
│           └── input.py        # Interactive TTY keyboard controls & optional pynput media keys
└── tests/
    ├── __init__.py
    ├── test_dsp.py             # Audio DSP mathematical formulas & filters
    ├── test_transitions.py     # All 8 DJ transitions
    ├── test_engine.py          # DecisionEngine spectral waterfall classification
    ├── test_cache.py           # Cache eviction and sliding window logic
    ├── test_playlist.py        # Playlist persistence and parsing
    └── test_ytm.py             # YouTube Music client mocks
```

---

## 4. Feature Specifications

### 4.1. Memory Optimization & Direct Stream / Save
- **`--no-mix`**: Uses `playback/direct.py`. MPV is invoked directly with native gapless playback (`--gapless-audio=yes`). Python memory footprint remains under 25 MB RSS.
- **`--stream`**: Plays directly via yt-dlp extracted audio stream URLs into MPV without writing files to disk or RAM.
- **`--save [DIR]`**: Enables file-by-file saving. Downloads songs with title metadata and tags into a user-specified folder rather than purging them after playback.
- **Sliding-Window Cache**: By default, only keeps the currently playing track and the next prefetched track on disk (`~/.cache/ytstr`). Finished tracks are automatically unlinked.

### 4.2. YouTube Music Integration & InnerTune/Metrolist GUI
- **`ytmusicapi` Integration**:
  - Connects to YouTube Music with or without authentication.
  - If authenticated: retrieves "Listen Again", "Quick Picks", user playlists, liked songs, and personalized history.
  - If unauthenticated: loads public explore feeds, charts, trending music, and search.
- **Lightweight GUI (`ytstr-gui` or `ytstr --gui`)**:
  - Built with native Python `tkinter` / `ttk` (zero heavy C++ dependencies like Qt or Chromium/Electron).
  - Modern YouTube Music dark aesthetic (obsidian background `#030303`, card tiles `#181818`, accent red `#FF0000`, clean typography).
  - Features:
    - Interactive search with instant result list.
    - Tabbed view: Home / Recommendations, Charts / Trending, Library, Search.
    - Login dialog: Guides OAuth authentication or cookie string import with step-by-step instructions.
    - Track actions: "Play in ytstr (Auto-DJ)", "Play (Light Mix)", "Stream Directly (No Mix)", "Save Track".

### 4.3. Packaging, Tooling, & Installer
- **`uv` Package Management**:
  - `pyproject.toml` standard configuration with entry points:
    - `ytstr = "ytstr.cli:main"`
    - `ytstr-gui = "ytstr.ytm.gui:main"`
- **`install.sh`**:
  - Checks for `mpv` and `ffmpeg` (prompts package manager if missing).
  - Checks for `uv` (installs `uv` via official curl if missing).
  - Installs `ytstr` via `uv tool install --force .` or links to `~/.local/bin/ytstr`.
  - Supports:
    ```bash
    curl -fsSL https://raw.githubusercontent.com/seeramsujay/ytstr/master/install.sh | bash
    ```

---

## 5. Staged Implementation & Commit Roadmap

| Stage | Commit Title | Scope of Work |
| :---: | :--- | :--- |
| **1** | `chore: configure uv packaging with pyproject.toml and project skeleton` | Initialize `pyproject.toml`, directory structure, `__init__.py` files, and `uv.lock`. |
| **2** | `refactor(audio): modularize DSP, DJ transitions, and DecisionEngine` | Migrate audio math, filters, 8 transition algorithms, and `DecisionEngine` into `ytstr.audio`; add unit tests. |
| **3** | `feat(cache): implement disk-backed bounded cache, --save, and --stream options` | Replace `/dev/shm` with sliding-window LRU disk cache; implement file-by-file saving and streaming. |
| **4** | `feat(playback): implement ultra-low RAM direct player for --no-mix mode` | Create `DirectPlayer` bypassing Python audio buffers; fix `--no-mix` high RAM usage; benchmark RSS. |
| **5** | `feat(ytm): add YouTube Music API client and authentication engine` | Implement `ytmusicapi` wrapper with OAuth/cookie support, personalized recommendations, and homepage browsing. |
| **6** | `feat(gui): implement lightweight InnerTune/Metrolist-style desktop GUI` | Build modern dark-theme Tkinter GUI for browsing YTM homepage, searching, logging in, and launching playback. |
| **7** | `feat(cli): wire unified CLI, terminal UI, and media key listener` | Integrate all modules into `ytstr.cli` and `ytstr.core.player`; preserve backward-compatible `./ytstr` entrypoint. |
| **8** | `ci: add comprehensive test suite and memory benchmarking scripts` | Add `pytest` test suite covering DSP, engine, cache, and CLI; update `test_mem.sh`. |
| **9** | `feat(install): add single-script install.sh and curl one-liner` | Create robust `install.sh` supporting system deps check, uv setup, and binary linking. |
| **10** | `docs: comprehensive documentation update and architecture guide` | Update `README.md`, docstrings, memory test results, and command usage. |

---

## 6. Verification & Memory Benchmark Criteria
1. **RAM Footprint Benchmark (`test_mem.sh`)**:
   - `--no-mix` Mode: RSS < 30 MB (down from 114 MB).
   - `--light-mix` Mode: RSS < 80 MB.
   - Auto-DJ Mode: RSS < 90 MB.
   - Disk Cache: No files left in `/dev/shm`; cache in `~/.cache/ytstr` strictly bounded.
2. **Feature Testing**:
   - `uv run pytest` passes 100% with high test coverage.
   - `--no-mix` works smoothly with skip, pause, seek, volume.
   - YouTube Music login and recommendations load properly in GUI and CLI.
   - `install.sh` runs cleanly in a fresh shell environment.
