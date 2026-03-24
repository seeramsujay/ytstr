#!/usr/bin/env python3
import sys
import os
import math
from pydub import AudioSegment

def get_equal_power_gain(t, duration, is_fade_in=True):
    """
    Calculates the dB gain needed for an equal power crossfade at time t.
    Equal power crossfades use a sine/cosine curve to ensure the combined
    power of both tracks remains constant (no volume dip in the middle).
    """
    # Normalize time from 0.0 to 1.0
    x = t / duration if duration > 0 else 0
    if not is_fade_in:
        x = 1.0 - x
        
    # Equal power multiplier: sin(x * pi/2)
    multiplier = math.sin(x * math.pi / 2.0)
    
    # Convert linear multiplier to decibels (pydub applies gain in dB)
    if multiplier <= 0:
        return -120.0 # Silence
    return 20 * math.log10(multiplier)

def equal_power_fade(audio: AudioSegment, duration_ms: int, is_fade_in: bool = True):
    """
    Applies an equal-power (sine curve) fade to avoid the classic 
    mid-transition volume dip associated with linear fades.
    """
    if len(audio) <= duration_ms:
        duration_ms = len(audio)
        
    # Process the fade in tiny 10ms chunks
    chunk_size = 10
    faded_chunks = []
    
    fade_audio = audio[:duration_ms] if is_fade_in else audio[-duration_ms:]
    remainder = audio[duration_ms:] if is_fade_in else audio[:-duration_ms]

    for i in range(0, len(fade_audio), chunk_size):
        chunk = fade_audio[i:i+chunk_size]
        t = i if is_fade_in else i + chunk_size
        
        # Calculate the equal power gain for this specific chunk
        gain = get_equal_power_gain(t, duration_ms, is_fade_in)
        faded_chunks.append(chunk.apply_gain(gain))
    
    faded_section = sum(faded_chunks)
    
    if is_fade_in:
        return faded_section + remainder
    else:
        return remainder + faded_section

def trim_to_energy(audio: AudioSegment, chunk_ms=100, threshold_ratio=0.6):
    """
    DJ AutoMix Trimming: Analyzes the overall RMS (energy) of the track 
    and chops off the low-energy atmospheric intros/outros until the audio 
    hits a percentage of its own average core energy.
    """
    avg_rms = audio.rms
    if avg_rms == 0: return audio # Avoid div-by-zero on silent tracks
    
    # We want chunks that hit at least X% of the track's average loudness
    threshold = avg_rms * threshold_ratio
    
    # Forward pass to find high-energy drop
    start_trim = 0
    for i in range(0, len(audio), chunk_ms):
        chunk = audio[i:i+chunk_ms]
        if chunk.rms >= threshold:
            start_trim = max(0, i - chunk_ms) # Keep 1 chunk of breathing room
            break
            
    # Backward pass to find high-energy end
    end_trim = len(audio)
    for i in range(len(audio), 0, -chunk_ms):
        chunk = audio[i-chunk_ms:i]
        if chunk.rms >= threshold:
            end_trim = min(len(audio), i + chunk_ms)
            break
            
    if start_trim >= end_trim:
        return audio # Fallback if math fails on a weird track
        
    print(f"  -> Stripped {start_trim}ms intro and {len(audio)-end_trim}ms outro fluff.")
    return audio[start_trim:end_trim]

def main():
    fade_ms = 3000 # 3 seconds aggressive DJ overlap
    
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        print("Loading Tracks...")
        t1 = AudioSegment.from_file("1.mp3")
        t2 = AudioSegment.from_file("2.mp3")
        t3 = AudioSegment.from_file("3.mp3")
        
        print("\nAnalyzing RMS Energy & Trimming to the drops...")
        t1 = trim_to_energy(t1)
        t2 = trim_to_energy(t2)
        t3 = trim_to_energy(t3)
    except Exception as e:
        print(f"Error loading files. Ensure 1.mp3, 2.mp3, and 3.mp3 exist.\nDetails: {e}")
        sys.exit(1)

    print(f"\nBaking {fade_ms}ms Equal-Power Overlaps...")

    # =========================================================
    # Track 1 Processing (1_mix.wav)
    # =========================================================
    t1_outro = equal_power_fade(t1[-fade_ms:], fade_ms, is_fade_in=False)
    t2_intro = equal_power_fade(t2[:fade_ms], fade_ms, is_fade_in=True)
    overlap_1 = t1_outro.overlay(t2_intro)
    
    out_1 = t1[:-fade_ms] + overlap_1

    # =========================================================
    # Track 2 Processing (2_mix.wav)
    # =========================================================
    t2_outro = equal_power_fade(t2[-fade_ms:], fade_ms, is_fade_in=False)
    t3_intro = equal_power_fade(t3[:fade_ms], fade_ms, is_fade_in=True)
    overlap_2 = t2_outro.overlay(t3_intro)
    
    # We drop t2[:fade_ms] because it was already baked into Track 1's outro
    out_2 = t2[fade_ms:-fade_ms] + overlap_2

    # =========================================================
    # Track 3 Processing (3_mix.wav)
    # =========================================================
    # We drop its first 3 seconds (baked into Track 2). No trailing overlap needed.
    out_3 = t3[fade_ms:]

    print("Exporting to lossless .WAV (Gapless Sequential Optimized)...")
    out_1.export("1_mix.wav", format="wav")
    out_2.export("2_mix.wav", format="wav")
    out_3.export("3_mix.wav", format="wav")
    
    print("\nComplete! To experience the high-energy DJ mix:")
    print("Run: mpv --gapless-audio=yes 1_mix.wav 2_mix.wav 3_mix.wav")

if __name__ == "__main__":
    main()
