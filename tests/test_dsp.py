"""
Unit tests for audio DSP mathematical functions and processing curves.
"""
import math
import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from ytstr.audio.dsp import (
    equal_power_fade,
    get_equal_power_gain,
    progressive_high_pass,
    safe_clamp_fade,
    tape_start_effect,
    tape_stop_effect,
    trim_to_energy,
)


def test_equal_power_gain():
    """Verify equal power gain curve boundaries."""
    # At t=0 for fade-in, gain is -120 dB (silence)
    gain_start = get_equal_power_gain(0, 1000, is_fade_in=True)
    assert gain_start <= -100.0

    # At t=duration for fade-in, gain is ~0 dB (full volume)
    gain_end = get_equal_power_gain(1000, 1000, is_fade_in=True)
    assert math.isclose(gain_end, 0.0, abs_tol=0.1)

    # At midpoint t=500, equal-power gain is -3 dB
    gain_mid = get_equal_power_gain(500, 1000, is_fade_in=True)
    assert math.isclose(gain_mid, -3.01, abs_tol=0.2)

    # For fade-out, curve is inverted
    gain_out_start = get_equal_power_gain(0, 1000, is_fade_in=False)
    assert math.isclose(gain_out_start, 0.0, abs_tol=0.1)
    gain_out_end = get_equal_power_gain(1000, 1000, is_fade_in=False)
    assert gain_out_end <= -100.0


def test_safe_clamp_fade():
    """Verify fade clamping never exceeds half the length of tracks."""
    seg1 = AudioSegment.silent(duration=4000)
    seg2 = AudioSegment.silent(duration=8000)

    # Half of seg1 is 2000ms, half of seg2 is 4000ms -> min is 2000ms
    assert safe_clamp_fade(5000, seg1, seg2) == 2000
    assert safe_clamp_fade(1000, seg1, seg2) == 1000
    assert safe_clamp_fade(1000, None, seg2) == 1000
    assert safe_clamp_fade(0, seg1, seg2) == 0


def test_equal_power_fade():
    """Verify equal_power_fade produces valid segments with correct duration."""
    tone = Sine(440).to_audio_segment(duration=1000)
    faded_in = equal_power_fade(tone, 500, is_fade_in=True)
    assert len(faded_in) == 1000
    # Initial 50ms should have much lower rms than the unaffected tail
    assert faded_in[:50].rms < faded_in[-50:].rms

    faded_out = equal_power_fade(tone, 500, is_fade_in=False)
    assert len(faded_out) == 1000
    assert faded_out[-50:].rms < faded_out[:50].rms


def test_tape_stop_and_start():
    """Verify tape stop and start effect algorithms run without crashing."""
    tone = Sine(440).to_audio_segment(duration=1000)
    stopped = tape_stop_effect(tone, 400)
    assert len(stopped) > 0

    started = tape_start_effect(tone, 400)
    assert len(started) > 0


def test_progressive_high_pass():
    """Verify progressive high pass returns matching or near matching duration."""
    tone = Sine(200).to_audio_segment(duration=500)
    filtered = progressive_high_pass(tone, 50, 500, steps=10)
    assert abs(len(filtered) - 500) <= 20


def test_trim_to_energy():
    """Verify silence trimming."""
    silence = AudioSegment.silent(duration=300)
    signal = Sine(440).to_audio_segment(duration=1000)
    combined = silence + signal + silence
    trimmed = trim_to_energy(combined, chunk_ms=50, threshold_ratio=0.3)
    assert len(trimmed) < len(combined)
