"""
Psychoacoustic DJ transition algorithms.

Implements all 8 transition styles:
- Fade: Classic equal-power crossfade (Pop, Rock, Vocals)
- Blend: Extended groove lock (EDM, House, Techno)
- Cut In: Beat-boundary cut with 15ms anti-pop micro-fade (Tempo/Genre changes)
- Rise: Progressive +4 dB drop swell (High-energy transitions)
- Bass Swap: High-pass sweep on outgoing + 120Hz kill on incoming (Basslines)
- Filter Wash: Resonant high-pass wash up to 2kHz (Complex outro masking)
- Melt: Multi-tap echo dissolve with low-pass softening (Ambient, Psychedelic, Lo-Fi)
- Tape Stop: Turntable motor warp crossfade (Universal safe fallback)
"""
from typing import Callable, Dict, Optional, Tuple
from pydub import AudioSegment
from pydub.effects import high_pass_filter, low_pass_filter

from ytstr.audio.dsp import (
    equal_power_fade,
    get_equal_power_gain,
    progressive_high_pass,
    safe_clamp_fade,
    tape_start_effect,
    tape_stop_effect,
)
from ytstr.core.types import TransitionType


def trans_fade(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Classic equal-power sinusoidal crossfade."""
    eff = safe_clamp_fade(fade_ms, current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    fout = equal_power_fade(current_song[-eff:], eff, is_fade_in=False)
    fin = equal_power_fade(next_song[:eff], eff, is_fade_in=True)
    return fout.overlay(fin), eff


def trans_blend(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Extended groove-lock blend (up to 10s) for steady rhythm matching."""
    blend_ms = min(10000, max(fade_ms * 3, 6000))
    eff = safe_clamp_fade(blend_ms, current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    fout = equal_power_fade(current_song[-eff:], eff, is_fade_in=False)
    fin = equal_power_fade(next_song[:eff], eff, is_fade_in=True)
    return fout.overlay(fin), eff


def trans_cut_in(
    current_song: AudioSegment, next_song: AudioSegment, _fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Immediate hard cut with 15ms anti-pop micro-fade."""
    guard_ms = 15
    if len(current_song) < guard_ms or len(next_song) < guard_ms:
        return AudioSegment.empty(), 0

    tail = current_song[-guard_ms:].fade_out(guard_ms)
    head = next_song[:guard_ms].fade_in(guard_ms)
    return tail.overlay(head), guard_ms


def trans_rise(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Equal-power crossfade combined with an active +4 dB gain swell on incoming."""
    eff = safe_clamp_fade(fade_ms, current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    fout = equal_power_fade(current_song[-eff:], eff, is_fade_in=False)

    chunk_size = 10
    in_audio = next_song[:eff]
    boosted_chunks = []
    for i in range(0, eff, chunk_size):
        chunk = in_audio[i:i + chunk_size]
        fade_gain = get_equal_power_gain(i, eff, is_fade_in=True)
        swell_db = 4.0 * (i / max(eff - 1, 1))
        boosted_chunks.append(chunk.apply_gain(fade_gain + swell_db))

    fin = sum(boosted_chunks) if boosted_chunks else in_audio
    return fout.overlay(fin), eff


def trans_bass_swap(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Progressive HP sweep (80->800 Hz) on outgoing with 120 Hz LF kill on incoming."""
    eff = safe_clamp_fade(fade_ms, current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    out_part = progressive_high_pass(current_song[-eff:], 80, 800, steps=25)
    out_part = equal_power_fade(out_part, eff, is_fade_in=False)

    try:
        in_cleaned = high_pass_filter(next_song[:eff], 120)
    except Exception:
        in_cleaned = next_song[:eff]

    in_part = equal_power_fade(in_cleaned, eff, is_fade_in=True)
    return out_part.overlay(in_part), eff


def trans_filter_wash(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Progressive HP sweep (80->2000 Hz) with 1-2 kHz resonance tracking."""
    wash_ms = min(fade_ms + 2000, len(current_song) // 2, len(next_song) // 2)
    if wash_ms <= 0:
        return AudioSegment.empty(), 0

    raw_out = current_song[-wash_ms:]
    out_part = progressive_high_pass(raw_out, 80, 2000, steps=30)

    try:
        resonance = high_pass_filter(low_pass_filter(raw_out, 2000), 1000) + 4
        half = wash_ms // 2
        silence = AudioSegment.silent(duration=half, frame_rate=raw_out.frame_rate)
        res_faded = silence + equal_power_fade(resonance[half:], wash_ms - half, is_fade_in=True)
        out_part = out_part.overlay(res_faded)
    except Exception:
        pass

    out_part = equal_power_fade(out_part, wash_ms, is_fade_in=False)
    in_part = equal_power_fade(next_song[:wash_ms], wash_ms, is_fade_in=True)
    return out_part.overlay(in_part), wash_ms


def trans_melt(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Multi-tap echo dissolve with 3 kHz low-pass atmospheric softening."""
    melt_ms = min(fade_ms + 4000, len(current_song) // 2, len(next_song) // 2)
    if melt_ms <= 0:
        return AudioSegment.empty(), 0

    out_part = current_song[-melt_ms:]
    echo_taps = [(200, -3), (400, -6), (700, -10)]
    for delay_ms, atten_db in echo_taps:
        if melt_ms > delay_ms * 2:
            echo = out_part + atten_db
            echo = AudioSegment.silent(duration=delay_ms) + echo[:-delay_ms]
            out_part = out_part.overlay(echo)

    try:
        out_part = low_pass_filter(out_part, 3000)
    except Exception:
        pass

    out_part = equal_power_fade(out_part, melt_ms, is_fade_in=False)
    in_part = equal_power_fade(next_song[:melt_ms], melt_ms, is_fade_in=True)
    return out_part.overlay(in_part), melt_ms


def trans_tape_stop(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Vinyl tape warp crossfade (outgoing winds down, incoming warps up)."""
    short_ms = min(1500, max(fade_ms, 800))
    eff = safe_clamp_fade(short_ms, current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    out_part = tape_stop_effect(current_song[-eff:], eff)
    in_part = tape_start_effect(next_song[:eff], eff)

    if len(out_part) > len(in_part):
        in_part = in_part + AudioSegment.silent(
            duration=len(out_part) - len(in_part), frame_rate=in_part.frame_rate
        )
    elif len(in_part) > len(out_part):
        out_part = out_part + AudioSegment.silent(
            duration=len(in_part) - len(out_part), frame_rate=out_part.frame_rate
        )

    return out_part.overlay(in_part), eff


TransitionHandler = Callable[[AudioSegment, AudioSegment, int], Tuple[AudioSegment, int]]

TRANSITIONS: Dict[str, TransitionHandler] = {
    TransitionType.FADE.value: trans_fade,
    TransitionType.BLEND.value: trans_blend,
    TransitionType.CUT_IN.value: trans_cut_in,
    TransitionType.RISE.value: trans_rise,
    TransitionType.BASS_SWAP.value: trans_bass_swap,
    TransitionType.FILTER_WASH.value: trans_filter_wash,
    TransitionType.MELT.value: trans_melt,
    TransitionType.TAPE_STOP.value: trans_tape_stop,
}


def apply_transition(
    trans_type: str,
    current_song: Optional[AudioSegment],
    next_song: Optional[AudioSegment],
    fade_ms: int
) -> Tuple[AudioSegment, int]:
    """
    Dispatch transition to appropriate handler function.

    Args:
        trans_type: Identifier of the transition (e.g. 'rise', 'bass_swap').
        current_song: Outgoing AudioSegment.
        next_song: Incoming AudioSegment.
        fade_ms: Base fade duration parameter.

    Returns:
        Tuple of (rendered overlap AudioSegment, effective consumed duration in ms).
    """
    if current_song is None or next_song is None:
        return AudioSegment.empty(), 0

    handler = TRANSITIONS.get(str(trans_type).lower(), trans_fade)
    return handler(current_song, next_song, fade_ms)
