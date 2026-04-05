# Future Roadmap & Planned Features for ytstr

This file outlines the definitive, step-by-step instructions for integrating the V2 `mixer` auto-DJ capabilities into the `ytstr` streamer. 

---

## Step 1: Core DSP & Decision Engine Porting ✅ DONE
**Goal:** Bring the psychoacoustic logic from `mixer` over to `ytstr`.
- ✅ Copied all 8 transition functions (`trans_fade`, `trans_blend`, `trans_rise`, `trans_cut_in`, `trans_bass_swap`, `trans_filter_wash`, `trans_melt`, `trans_tape_stop`) from `mixer`.
- ✅ Copied DSP utilities: `progressive_high_pass`, `safe_clamp_fade`, `tape_stop_effect`, `tape_start_effect`.
- ✅ Ported the `DecisionEngine` class verbatim with 5-second energy/spectral analysis windows.
- ✅ Ensured compatibility with `ytstr`'s lazy chunk-and-overlap architecture.

## Step 2: Transition Logic & CLI Arguments ✅ DONE
**Goal:** Implement flexible CLI controls (`--no-mix`, `--light-mix`, and default auto-DJ).
- ✅ **Default (no flags):** `ytstr` passes downloaded audio to `DecisionEngine`, determines the optimal transition, and bakes it.
- ✅ **`--light-mix`:** Skips `DecisionEngine` and always applies equal-power crossfade.
- ✅ **`--no-mix`:** Totally skips `pydub` mixing and queues raw audio directly.

## Step 3: Media Control Synchronization ✅ DONE
**Goal:** Implement robust, system-wide media playback hooks.
- ✅ Ported the `pynput` listener logic from `mixer`/`lightMixer` to `ytstr`.
- ✅ Supports F7/F8/F9 alongside hardware media keys via the `mpv` IPC socket.
- ✅ Graceful fallback if `pynput` is not installed.

## Step 4: Documentation Audit ✅ DONE
**Goal:** Update all user-facing documentation.
- ✅ `README.md` fully rewritten with transition table, architecture diagram, and all flags.
- ✅ `CHANGELOG.md` documenting V3→V4 feature jump.
- ✅ Standalone `mixer`/`lightMixer` archived to `Archives/mixer_legacy/`.
- ✅ `roadmap.md` updated to reflect V4 completion.

---

## Future: V5 Intelligence Upgrades
- BPM-aware blend duration
- Harmonic key detection (Camelot Wheel)
- Onset-snapped cut-in timing
- Graph-based playlist reordering
