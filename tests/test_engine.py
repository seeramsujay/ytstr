"""
Unit tests for spectral DecisionEngine feature analysis and decision rules.
"""
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

from ytstr.audio.engine import DecisionEngine


def test_analyze_chunk_silence():
    engine = DecisionEngine(window_ms=2000)
    silence = AudioSegment.silent(duration=2000)
    rms, bass, treble, var = engine.analyze_chunk(silence)
    assert rms == 0.0
    assert bass == 0.0
    assert treble == 0.0
    assert var == 0.0


def test_analyze_chunk_tone():
    engine = DecisionEngine(window_ms=2000)
    bass_tone = Sine(100).to_audio_segment(duration=2000)
    rms, bass, treble, var = engine.analyze_chunk(bass_tone)
    assert rms > 0.0
    assert bass > 0.0


def test_select_transition_rise():
    """Rule 1: If incoming is significantly louder, select rise."""
    engine = DecisionEngine(window_ms=2000)
    quiet_out = Sine(440).to_audio_segment(duration=3000).apply_gain(-20)
    loud_in = Sine(440).to_audio_segment(duration=3000).apply_gain(0)
    rule = engine.select_transition(quiet_out, loud_in)
    assert rule in ["rise", "cut_in"]


def test_select_transition_none():
    """Verify empty/None inputs fall back to fade."""
    engine = DecisionEngine(window_ms=2000)
    assert engine.select_transition(None, None) == "fade"
    tone = Sine(440).to_audio_segment(duration=2000)
    assert engine.select_transition(tone, None) == "fade"
    assert engine.select_transition(None, tone) == "fade"
