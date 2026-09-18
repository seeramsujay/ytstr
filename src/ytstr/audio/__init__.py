"""
Audio processing, DSP routines, transitions, and decision engine for ytstr.
"""
from ytstr.audio.dsp import (
    equal_power_fade,
    get_audio_chunk,
    get_audio_duration,
    get_equal_power_gain,
    progressive_high_pass,
    safe_clamp_fade,
    tape_start_effect,
    tape_stop_effect,
    trim_to_energy,
)
from ytstr.audio.engine import DecisionEngine
from ytstr.audio.transitions import (
    TRANSITIONS,
    apply_transition,
    trans_bass_swap,
    trans_blend,
    trans_cut_in,
    trans_fade,
    trans_filter_wash,
    trans_melt,
    trans_rise,
    trans_tape_stop,
)

__all__ = [
    "equal_power_fade",
    "get_audio_chunk",
    "get_audio_duration",
    "get_equal_power_gain",
    "progressive_high_pass",
    "safe_clamp_fade",
    "tape_start_effect",
    "tape_stop_effect",
    "trim_to_energy",
    "DecisionEngine",
    "TRANSITIONS",
    "apply_transition",
    "trans_bass_swap",
    "trans_blend",
    "trans_cut_in",
    "trans_fade",
    "trans_filter_wash",
    "trans_melt",
    "trans_rise",
    "trans_tape_stop",
]
