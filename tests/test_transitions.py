"""
Unit tests for all 8 DJ transitions and transition dispatching.
"""
from pydub import AudioSegment
from pydub.generators import Sine

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


def create_test_tracks(duration_ms=6000):
    t1 = Sine(300).to_audio_segment(duration=duration_ms)
    t2 = Sine(600).to_audio_segment(duration=duration_ms)
    return t1, t2


def test_transitions_dispatch_all():
    """Verify all 8 transition keys are registered in the dispatch table."""
    expected_keys = [
        "fade", "blend", "cut_in", "rise", "bass_swap",
        "filter_wash", "melt", "tape_stop"
    ]
    for k in expected_keys:
        assert k in TRANSITIONS


def test_trans_fade():
    t1, t2 = create_test_tracks()
    overlap, eff = trans_fade(t1, t2, 2000)
    assert eff == 2000
    assert len(overlap) == 2000


def test_trans_cut_in():
    t1, t2 = create_test_tracks()
    overlap, eff = trans_cut_in(t1, t2, 2000)
    assert eff == 15
    assert len(overlap) == 15


def test_trans_blend():
    t1, t2 = create_test_tracks(8000)
    overlap, eff = trans_blend(t1, t2, 2000)
    assert eff > 0
    assert len(overlap) == eff


def test_trans_rise():
    t1, t2 = create_test_tracks()
    overlap, eff = trans_rise(t1, t2, 2000)
    assert eff == 2000
    assert len(overlap) == 2000


def test_trans_bass_swap():
    t1, t2 = create_test_tracks()
    overlap, eff = trans_bass_swap(t1, t2, 2000)
    assert eff == 2000
    assert len(overlap) == 2000


def test_trans_filter_wash():
    t1, t2 = create_test_tracks(10000)
    overlap, eff = trans_filter_wash(t1, t2, 2000)
    assert eff > 0
    assert len(overlap) == eff


def test_trans_melt():
    t1, t2 = create_test_tracks(12000)
    overlap, eff = trans_melt(t1, t2, 2000)
    assert eff > 0
    assert len(overlap) == eff


def test_trans_tape_stop():
    t1, t2 = create_test_tracks()
    overlap, eff = trans_tape_stop(t1, t2, 1200)
    assert eff > 0
    assert len(overlap) >= eff


def test_apply_transition_fallback():
    """Verify unknown transition names fall back gracefully to trans_fade."""
    t1, t2 = create_test_tracks()
    overlap, eff = apply_transition("unknown_style", t1, t2, 2000)
    assert eff == 2000
    assert len(overlap) == 2000

    # Test None track handling
    empty_overlap, empty_eff = apply_transition("fade", None, t2, 2000)
    assert empty_eff == 0
    assert len(empty_overlap) == 0
