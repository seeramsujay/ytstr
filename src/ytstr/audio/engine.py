"""
Spectral Energy Decision Engine for intelligent DJ transitions.

Analyzes 5-second acoustic handoff windows at the end of the outgoing track
and start of the incoming track to select the optimal transition style.
"""
from typing import Optional, Tuple
from pydub import AudioSegment
from pydub.effects import high_pass_filter, low_pass_filter

from ytstr.config import ANALYSIS_WINDOW_MS
from ytstr.core.types import TransitionType


class DecisionEngine:
    """
    Automatic DJ transition selector using spectral energy analysis.

    Extracts four key acoustic features:
    - rms: Total signal mono amplitude / energy.
    - bass_rms: Sub-250 Hz energy (kick drums, 808s, basslines).
    - treble_rms: High frequency energy above 2 kHz (cymbals, vocals, synths).
    - variance: Energy deviation across 500 ms slices (steady groove vs chaotic).
    """

    def __init__(self, window_ms: int = ANALYSIS_WINDOW_MS):
        self.window_ms = window_ms

    def analyze_chunk(self, chunk: Optional[AudioSegment]) -> Tuple[float, float, float, float]:
        """
        Extract (rms, bass_rms, treble_rms, energy_variance) from audio chunk.

        Args:
            chunk: AudioSegment to analyze.

        Returns:
            Tuple of (rms, bass_rms, treble_rms, variance).
        """
        if chunk is None or len(chunk) == 0:
            return 0.0, 0.0, 0.0, 0.0

        rms = float(chunk.rms)
        if rms == 0.0:
            return 0.0, 0.0, 0.0, 0.0

        try:
            bass = float(low_pass_filter(chunk, 250).rms)
        except Exception:
            bass = rms

        try:
            treble = float(high_pass_filter(chunk, 2000).rms)
        except Exception:
            treble = rms

        window_ms = 500
        energies = [
            float(chunk[i:i + window_ms].rms)
            for i in range(0, len(chunk), window_ms)
        ]
        if len(energies) > 1:
            mean = sum(energies) / len(energies)
            variance = sum((e - mean) ** 2 for e in energies) / len(energies)
        else:
            variance = 0.0

        return rms, bass, treble, variance

    def select_transition(
        self, current_song: Optional[AudioSegment], next_song: Optional[AudioSegment]
    ) -> str:
        """
        Select the best-fit DJ transition style for the boundary between two tracks.

        Args:
            current_song: Outgoing AudioSegment.
            next_song: Incoming AudioSegment.

        Returns:
            Transition name string (e.g. 'rise', 'bass_swap', 'melt', 'fade').
        """
        if current_song is None or next_song is None:
            return TransitionType.FADE.value

        win_a = min(self.window_ms, len(current_song))
        win_b = min(self.window_ms, len(next_song))

        if win_a == 0 or win_b == 0:
            return TransitionType.FADE.value

        a_rms, a_bass, a_treble, a_var = self.analyze_chunk(current_song[-win_a:])
        b_rms, b_bass, b_treble, b_var = self.analyze_chunk(next_song[:win_b])

        if a_rms == 0.0 or b_rms == 0.0:
            return TransitionType.FADE.value

        # Rule 1: Energy Surge / Beat Drop -> Rise
        if b_rms > a_rms * 1.8:
            return TransitionType.RISE.value

        # Rule 2: Sharp contrast in profile or dynamics -> Tape Stop
        rms_ratio = max(a_rms, 1.0) / max(b_rms, 1.0)
        a_profile = a_bass / max(a_treble, 1.0)
        b_profile = b_bass / max(b_treble, 1.0)

        if (
            rms_ratio > 3.0
            or rms_ratio < (1.0 / 3.0)
            or (max(a_var, 1.0) / max(b_var, 1.0)) > 4.0
            or (max(b_var, 1.0) / max(a_var, 1.0)) > 4.0
            or (max(a_profile, 0.1) / max(b_profile, 0.1)) > 2.5
            or (max(b_profile, 0.1) / max(a_profile, 0.1)) > 2.5
        ):
            return TransitionType.TAPE_STOP.value

        # Rule 3: Both tracks bass-heavy -> Bass Swap (prevents low-end mud)
        if (a_bass / a_rms) > 0.40 and (b_bass / b_rms) > 0.40:
            return TransitionType.BASS_SWAP.value

        # Rule 4: Outgoing is treble-dominated -> Filter Wash
        if a_treble > a_bass * 1.8 and a_bass > 0:
            return TransitionType.FILTER_WASH.value

        # Rule 5: Outgoing is quiet / decaying -> Cut In
        if a_rms < b_rms * 0.25:
            return TransitionType.CUT_IN.value

        # Rule 6: Outgoing energy is erratic/chaotic -> Melt
        if a_var > (a_rms ** 2) * 0.4:
            return TransitionType.MELT.value

        # Rule 7: Both tracks steady groove -> Blend
        if a_var < (a_rms ** 2) * 0.08 and b_var < (b_rms ** 2) * 0.08:
            return TransitionType.BLEND.value

        # Default fallback: safe equal-power crossfade
        return TransitionType.FADE.value
