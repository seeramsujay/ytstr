# ytstr — Project Diary & Roadmap

A chronological log of decisions, implementations, and milestones for `ytstr`.

---

## V1–V3: Lightweight YouTube Streamer
- **Goal:** Create a terminal-native, lightweight playlist streamer for YouTube using `yt-dlp`.
- Implemented gapless `mpv` streaming using IPC sockets and `--gapless-audio=yes`.
- Implemented RAM disk caching (`/dev/shm`) and lazy physical audio splicing via `pydub`.
- Implemented simple equal-power (sinusoidal) crossfades for seamless track transitions.
- Added `--no-mix` for playing tracks sequentially without any overlapping crossfade logic.
- Included UI threading to display the currently playing track and the upcoming track cleanly in the terminal.

---

## V4: Integration with Mixer's Decision Engine ✅ COMPLETED
- **Goal:** Port the intelligent spectral `DecisionEngine` from the `mixer` project into `ytstr` to turn it into an advanced auto-DJ.
- ✅ Incorporated psychoacoustic transition algorithms: Rise, Bass Swap, Filter Wash, Cut In, Melt, Tape Stop, Blend, and Fade.
- ✅ Added `--light-mix` argument to allow falling back to the V1 equal-power crossfade (bypassing spectral analysis).
- ✅ Kept `--no-mix` intact as the purest form of sequential playback.
- ✅ Brought over global `pynput` media key interception (Play/Pause, Prev, Next).
- ✅ Archived standalone `mixer` and `lightMixer` scripts to `Archives/mixer_legacy/`.
- ✅ Added transition-type display in the terminal UI.
- ✅ Updated README, CHANGELOG, and requirements.txt.

---

## [Future] V5: Intelligence Upgrades
- BPM-aware blend duration (longer blends for matched BPMs).
- Harmonic key detection (Camelot Wheel) to prefer consonant transitions.
- Onset-snapped cut-in timing so hard cuts land on beat boundaries.
- Graph-based playlist reordering (energy/key/BPM distance optimisation).
