"""
Digital Signal Processing (DSP) and psychoacoustic mathematical routines.

Contains equal-power fading curves, progressive filter sweeps, tape warp simulations,
and ffmpeg audio demuxing helpers.
"""
import io
import math
import subprocess
from typing import Optional
from pydub import AudioSegment
from pydub.effects import high_pass_filter


def get_audio_duration(file_path: str) -> float:
    """
    Probe the duration of an audio file in seconds via ffprobe.

    Args:
        file_path: Absolute or relative path to media file.

    Returns:
        Duration in seconds as float, or 0.0 if probing fails.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        res = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        return float(res)
    except Exception:
        return 0.0


def get_audio_chunk(file_path: str, start_s: float, duration_s: float) -> AudioSegment:
    """
    Extract a slice of audio from disk into an in-memory 16-bit 44.1kHz stereo AudioSegment.

    Args:
        file_path: Path to the media file.
        start_s: Seek offset in seconds.
        duration_s: Duration in seconds to extract.

    Returns:
        AudioSegment object, or AudioSegment.empty() on failure.
    """
    if duration_s <= 0:
        return AudioSegment.empty()

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", str(max(0.0, start_s)),
        "-t", str(duration_s),
        "-i", file_path,
        "-f", "wav",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        "pipe:1"
    ]
    try:
        res = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return AudioSegment.from_file(io.BytesIO(res), format="wav")
    except Exception:
        return AudioSegment.empty()


def get_equal_power_gain(t: float, duration: float, is_fade_in: bool = True) -> float:
    """
    Return a dB gain value for a single point on an equal-power fade curve.

    The curve follows a quarter-cosine (sin²) power law, keeping the perceived
    combined loudness constant during a crossfade.

    Args:
        t: Current position in milliseconds.
        duration: Total fade duration in milliseconds.
        is_fade_in: True for fade-in (silence -> 0 dB), False for fade-out (0 dB -> silence).

    Returns:
        Gain in decibels (clamped to -120 dB at minimum).
    """
    if duration <= 0:
        return 0.0 if is_fade_in else -120.0

    x = max(0.0, min(1.0, t / duration))
    if not is_fade_in:
        x = 1.0 - x

    multiplier = math.sin(x * math.pi / 2.0)
    if multiplier <= 1e-6:
        return -120.0
    return 20.0 * math.log10(multiplier)


def equal_power_fade(audio: AudioSegment, duration_ms: int, is_fade_in: bool = True) -> AudioSegment:
    """
    Apply a psychoacoustic equal-power (sinusoidal) fade to an AudioSegment.

    Args:
        audio: Source AudioSegment.
        duration_ms: Duration of the fade window in milliseconds.
        is_fade_in: True for fade-in, False for fade-out.

    Returns:
        New AudioSegment with equal-power gain applied.
    """
    if duration_ms <= 0 or len(audio) == 0:
        return audio

    eff_ms = min(duration_ms, len(audio))
    chunk_size = 10  # 10 ms grain resolution

    fade_audio = audio[:eff_ms] if is_fade_in else audio[-eff_ms:]
    remainder = audio[eff_ms:] if is_fade_in else audio[:-eff_ms]

    faded_chunks = []
    for i in range(0, len(fade_audio), chunk_size):
        chunk = fade_audio[i:i + chunk_size]
        t = i if is_fade_in else i + chunk_size
        gain = get_equal_power_gain(t, eff_ms, is_fade_in)
        faded_chunks.append(chunk.apply_gain(gain))

    faded_section = sum(faded_chunks) if faded_chunks else AudioSegment.empty()
    return (faded_section + remainder) if is_fade_in else (remainder + faded_section)


def safe_clamp_fade(duration_ms: int, *tracks: Optional[AudioSegment]) -> int:
    """
    Clamp desired fade duration so it never exceeds half of any track's total length.

    Args:
        duration_ms: Intended transition length.
        *tracks: AudioSegments being crossfaded.

    Returns:
        Clamped duration in milliseconds >= 0.
    """
    result = duration_ms
    for t in tracks:
        if t is not None and len(t) > 0:
            result = min(result, len(t) // 2)
    return max(result, 0)


def progressive_high_pass(audio: AudioSegment, start_hz: int, end_hz: int, steps: int = 20) -> AudioSegment:
    """
    Apply a progressive high-pass filter sweep across the duration of an audio segment.

    Simulates a DJ sweeping the HP filter knob to progressively remove low frequencies.

    Args:
        audio: Source AudioSegment.
        start_hz: Initial cutoff frequency in Hz.
        end_hz: Final cutoff frequency in Hz.
        steps: Number of discrete interpolation slices.

    Returns:
        Progressively filtered AudioSegment.
    """
    if len(audio) == 0 or steps <= 0:
        return audio

    step_len = len(audio) // steps
    if step_len == 0:
        return audio

    parts = []
    for i in range(steps):
        ratio = i / max(steps - 1, 1)
        # Logarithmic frequency interpolation
        cutoff = int(start_hz * (end_hz / start_hz) ** ratio)
        cutoff = max(cutoff, 20)
        chunk = audio[i * step_len:(i + 1) * step_len]
        try:
            chunk = high_pass_filter(chunk, cutoff)
        except Exception:
            pass
        parts.append(chunk)

    leftover = audio[steps * step_len:]
    if len(leftover) > 0:
        try:
            leftover = high_pass_filter(leftover, end_hz)
        except Exception:
            pass
        parts.append(leftover)

    return sum(parts) if parts else audio


def tape_stop_effect(audio: AudioSegment, duration_ms: int) -> AudioSegment:
    """
    Simulate progressive turntable motor power-down (tape stop).

    Slows playback speed from 100% down to 10% while progressively dropping volume.

    Args:
        audio: Source AudioSegment.
        duration_ms: Duration of the stop effect in milliseconds.

    Returns:
        AudioSegment ending with simulated vinyl power down.
    """
    if len(audio) == 0 or duration_ms <= 0:
        return audio

    eff_ms = min(duration_ms, len(audio))
    head = audio[:-eff_ms]
    tail = audio[-eff_ms:]

    steps = 20
    chunk_len = len(tail) // steps
    if chunk_len == 0:
        return audio

    parts = []
    for i in range(steps):
        chunk = tail[i * chunk_len:(i + 1) * chunk_len]
        ratio = 1.0 - (i / steps) * 0.9  # 100% -> 10% speed
        new_frame_rate = max(int(chunk.frame_rate * ratio), 1000)

        try:
            slowed = chunk._spawn(chunk.raw_data, overrides={
                "frame_rate": new_frame_rate
            }).set_frame_rate(chunk.frame_rate)
        except Exception:
            slowed = chunk

        vol_drop = - (i / steps) * 15.0  # Drop up to -15dB
        parts.append(slowed + vol_drop)

    leftover = tail[steps * chunk_len:]
    if len(leftover) > 0:
        parts.append(leftover - 15.0)

    res = sum(parts) if parts else tail
    res = res.fade_out(min(200, len(res)))
    return head + res


def tape_start_effect(audio: AudioSegment, duration_ms: int) -> AudioSegment:
    """
    Simulate progressive turntable spin-up (tape start).

    Accelerates playback speed from 10% up to 100% while ramping volume up to 0 dB.

    Args:
        audio: Source AudioSegment.
        duration_ms: Duration of spin-up effect in milliseconds.

    Returns:
        AudioSegment starting with simulated vinyl power up.
    """
    if len(audio) == 0 or duration_ms <= 0:
        return audio

    eff_ms = min(duration_ms, len(audio))
    head = audio[:eff_ms]
    tail = audio[eff_ms:]

    steps = 20
    chunk_len = len(head) // steps
    if chunk_len == 0:
        return audio

    parts = []
    for i in range(steps):
        chunk = head[i * chunk_len:(i + 1) * chunk_len]
        ratio = 0.1 + (i / steps) * 0.9  # 10% -> 100% speed
        new_frame_rate = max(int(chunk.frame_rate * ratio), 1000)

        try:
            sped = chunk._spawn(chunk.raw_data, overrides={
                "frame_rate": new_frame_rate
            }).set_frame_rate(chunk.frame_rate)
        except Exception:
            sped = chunk

        vol_boost = -15.0 * (1.0 - (i / steps))  # -15dB -> 0dB
        parts.append(sped + vol_boost)

    leftover = head[steps * chunk_len:]
    if len(leftover) > 0:
        parts.append(leftover)

    res = sum(parts) if parts else head
    res = res.fade_in(min(200, len(res)))
    return res + tail


def trim_to_energy(audio: AudioSegment, chunk_ms: int = 100, threshold_ratio: float = 0.5) -> AudioSegment:
    """
    Strip leading and trailing low-energy silence/fluff using RMS thresholding.

    Args:
        audio: Source AudioSegment.
        chunk_ms: Scanning grain in milliseconds.
        threshold_ratio: Fraction of average RMS to treat as signal threshold.

    Returns:
        Trimmed AudioSegment.
    """
    avg_rms = audio.rms
    if avg_rms == 0:
        return audio

    threshold = avg_rms * threshold_ratio

    start_trim = 0
    for i in range(0, len(audio), chunk_ms):
        if audio[i:i + chunk_ms].rms >= threshold:
            start_trim = max(0, i - chunk_ms)
            break

    end_trim = len(audio)
    for i in range(len(audio), 0, -chunk_ms):
        if audio[i - chunk_ms:i].rms >= threshold:
            end_trim = min(len(audio), i + chunk_ms)
            break

    if start_trim >= end_trim:
        return audio

    return audio[start_trim:end_trim]
