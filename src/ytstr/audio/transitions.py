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

Each transition receives the outgoing track's tail window (current_song) and the
incoming track's head window (next_song) and returns (overlap, consumed_ms):
the rendered overlap audio, and how many ms of each window it used. The caller
plays the outgoing track up to its last consumed_ms, then the overlap, then
resumes the incoming track at consumed_ms.
"""
from typing import Callable, Dict, Optional, Tuple
from pydub import AudioSegment

from ytstr.audio.dsp import (
    apply_gain_curve,
    equal_power_fade,
    get_equal_power_gain,
    high_pass,
    low_pass,
    progressive_high_pass,
    tape_start_effect,
    tape_stop_effect,
)
from ytstr.core.types import TransitionType

CUT_IN_GUARD_MS = 15


def _blend_ms(fade_ms: int) -> int:
    return min(10000, max(fade_ms * 3, 6000))


def _tape_ms(fade_ms: int) -> int:
    return min(1500, max(fade_ms, 800))


def transition_window_ms(trans_type: str, fade_ms: int) -> int:
    """Length of audio each transition needs from the outgoing tail and incoming head."""
    trans_type = str(trans_type).lower()
    if trans_type == TransitionType.BLEND.value:
        return _blend_ms(fade_ms)
    if trans_type == TransitionType.CUT_IN.value:
        return CUT_IN_GUARD_MS
    if trans_type == TransitionType.FILTER_WASH.value:
        return fade_ms + 2000
    if trans_type == TransitionType.MELT.value:
        return fade_ms + 4000
    if trans_type == TransitionType.TAPE_STOP.value:
        return _tape_ms(fade_ms)
    return fade_ms  # fade, rise, bass_swap


def max_transition_window_ms(fade_ms: int) -> int:
    """Largest window any transition may need (tail reserve for Auto-DJ mode)."""
    return max(transition_window_ms(t.value, fade_ms) for t in TransitionType)


def _window(duration_ms: int, current_song: AudioSegment, next_song: AudioSegment) -> int:
    """Clamp a transition length to the audio actually available in both windows."""
    return max(0, min(duration_ms, len(current_song), len(next_song)))


def ffmpeg_band(audio: AudioSegment) -> AudioSegment:
    """1-2 kHz resonance band (2 kHz low-pass followed by 1 kHz high-pass)."""
    return high_pass(low_pass(audio, 2000), 1000)


def trans_fade(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Classic equal-power sinusoidal crossfade."""
    eff = _window(fade_ms, current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    fout = equal_power_fade(current_song[-eff:], eff, is_fade_in=False)
    fin = equal_power_fade(next_song[:eff], eff, is_fade_in=True)
    return fout.overlay(fin), eff


def trans_blend(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Extended groove-lock blend (up to 10s) for steady rhythm matching."""
    eff = _window(_blend_ms(fade_ms), current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    fout = equal_power_fade(current_song[-eff:], eff, is_fade_in=False)
    fin = equal_power_fade(next_song[:eff], eff, is_fade_in=True)
    return fout.overlay(fin), eff


def trans_cut_in(
    current_song: AudioSegment, next_song: AudioSegment, _fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Immediate hard cut with 15ms anti-pop micro-fade."""
    guard_ms = CUT_IN_GUARD_MS
    if len(current_song) < guard_ms or len(next_song) < guard_ms:
        return AudioSegment.empty(), 0

    tail = current_song[-guard_ms:].fade_out(guard_ms)
    head = next_song[:guard_ms].fade_in(guard_ms)
    return tail.overlay(head), guard_ms


def trans_rise(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Equal-power crossfade combined with an active +4 dB gain swell on incoming."""
    eff = _window(fade_ms, current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    fout = equal_power_fade(current_song[-eff:], eff, is_fade_in=False)

    def swell_gain(i: int) -> float:
        return get_equal_power_gain(i, eff, is_fade_in=True) + 4.0 * (i / max(eff - 1, 1))

    fin = apply_gain_curve(next_song[:eff], swell_gain, 10)
    return fout.overlay(fin), eff


def trans_bass_swap(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Progressive HP sweep (80->800 Hz) on outgoing with 120 Hz LF kill on incoming."""
    eff = _window(fade_ms, current_song, next_song)
    if eff == 0:
        return AudioSegment.empty(), 0

    out_part = progressive_high_pass(current_song[-eff:], 80, 800, steps=25)
    out_part = equal_power_fade(out_part, eff, is_fade_in=False)

    in_cleaned = high_pass(next_song[:eff], 120)

    in_part = equal_power_fade(in_cleaned, eff, is_fade_in=True)
    return out_part.overlay(in_part), eff


def trans_filter_wash(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Progressive HP sweep (80->2000 Hz) with 1-2 kHz resonance tracking."""
    wash_ms = _window(fade_ms + 2000, current_song, next_song)
    if wash_ms <= 0:
        return AudioSegment.empty(), 0

    raw_out = current_song[-wash_ms:]
    out_part = progressive_high_pass(raw_out, 80, 2000, steps=30)

    try:
        resonance = ffmpeg_band(raw_out) + 4
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
    melt_ms = _window(fade_ms + 4000, current_song, next_song)
    if melt_ms <= 0:
        return AudioSegment.empty(), 0

    out_part = current_song[-melt_ms:]
    echo_taps = [(200, -3), (400, -6), (700, -10)]
    for delay_ms, atten_db in echo_taps:
        if melt_ms > delay_ms * 2:
            echo = out_part + atten_db
            echo = AudioSegment.silent(duration=delay_ms) + echo[:-delay_ms]
            out_part = out_part.overlay(echo)

    out_part = low_pass(out_part, 3000)

    out_part = equal_power_fade(out_part, melt_ms, is_fade_in=False)
    in_part = equal_power_fade(next_song[:melt_ms], melt_ms, is_fade_in=True)
    return out_part.overlay(in_part), melt_ms


def trans_tape_stop(
    current_song: AudioSegment, next_song: AudioSegment, fade_ms: int
) -> Tuple[AudioSegment, int]:
    """Vinyl tape warp crossfade (outgoing winds down, incoming warps up)."""
    eff = _window(_tape_ms(fade_ms), current_song, next_song)
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
