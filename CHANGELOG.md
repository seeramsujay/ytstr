# Changelog

All notable changes to this project will be documented in this file.

## [4.0.0] - 2026-04-05

### Added
- **V2 DecisionEngine Integration** — Ported the full psychoacoustic spectral analysis engine from the standalone `mixer` project. The engine analyses a 5-second window at both ends of every track pair and selects the optimal transition from 8 styles.
- **8 Transition Styles** — `fade`, `blend`, `rise`, `cut_in`, `bass_swap`, `filter_wash`, `melt`, `tape_stop` — each with its own psychoacoustic trigger condition.
- **`--light-mix` flag** — Falls back to a simple equal-power crossfade without running the DecisionEngine. Good for low-CPU playback.
- **Global Media Key Hooks** — `pynput` integration for hardware Play/Pause (F8), Next (F9), Previous (F7), and system media keys.
- **Mix Mode Display** — Startup shows which mixing mode is active (Auto-DJ / Light Mix / OFF).
- **Transition Logging** — Each baked transition logs its type to stderr and the "PLAYING" UI shows which transition was used.

### Changed
- Version bumped to 4.0.0 to reflect the `mixer` integration.
- Standalone `mixer` and `lightMixer` scripts archived to `Archives/mixer_legacy/` — their functionality is now fully embedded in `ytstr`.
- `requirements.txt` now includes `yt-dlp` and `pynput`.

### Removed
- Standalone `mixer` and `lightMixer` scripts from root (moved to `Archives/mixer_legacy/`).

## [3.0.0] - 2026-03-24

### Added
- Initial `ytstr` implementation with `yt-dlp` + `mpv` IPC streaming.
- RAM disk caching in `/dev/shm`.
- Simple equal-power crossfade via `pydub`.
- `--no-mix` and `--no-shuffle` flags.
- Playlist management (`--add`, `--list`, `--remove`).
