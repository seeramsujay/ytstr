#!/usr/bin/env python3
import sys
import os
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

def trim_silence(audio: AudioSegment, silence_threshold=-45.0, chunk_size=10):
    """
    Finds the true start and end of the audio by calculating the exact milliseconds 
    where the audio energy exceeds the Spotify-esque -45 dBFS threshold.
    """
    # 1. Trim leading silence
    start_trim = detect_leading_silence(
        audio, 
        silence_threshold=silence_threshold, 
        chunk_size=chunk_size
    )
    trimmed_start = audio[start_trim:]
    
    # 2. Trim trailing silence (by detecting leading silence on the reversed track)
    end_trim = detect_leading_silence(
        trimmed_start.reverse(), 
        silence_threshold=silence_threshold, 
        chunk_size=chunk_size
    )
    
    if end_trim > 0:
        return trimmed_start[:-end_trim]
    return trimmed_start

def main():
    fade_ms = 5000
    
    # Ensure working directory is the script directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        print("Loading and stripping silence from tracks...")
        t1 = trim_silence(AudioSegment.from_file("1.mp3"))
        t2 = trim_silence(AudioSegment.from_file("2.mp3"))
        t3 = trim_silence(AudioSegment.from_file("3.mp3"))
    except FileNotFoundError as e:
        print(f"Error loading files. Ensure 1.mp3, 2.mp3, and 3.mp3 exist in the mixer directory.\nDetails: {e}")
        sys.exit(1)

    print(f"Baking structural {fade_ms}ms overlaps...")

    # =========================================================
    # Track 1 Processing (1_mix.mp3)
    # =========================================================
    # Slicing the very last 5 seconds of Track 1 and fading it out
    t1_outro = t1[-fade_ms:].fade_out(fade_ms)
    
    # Slicing the first 5 seconds of Track 2 and fading it in
    t2_intro = t2[:fade_ms].fade_in(fade_ms)
    
    # Physically combining both audio energies into a single 5-second chunk
    overlap_1 = t1_outro.overlay(t2_intro)
    
    # Final Track 1 = (Track 1 up until the last 5 seconds) + (The baked 5s overlap)
    out_1 = t1[:-fade_ms] + overlap_1

    # =========================================================
    # Track 2 Processing (2_mix.mp3)
    # =========================================================
    # Slicing the very last 5 seconds of Track 2 and fading it out
    t2_outro = t2[-fade_ms:].fade_out(fade_ms)
    
    # Slicing the first 5 seconds of Track 3 and fading it in
    t3_intro = t3[:fade_ms].fade_in(fade_ms)
    
    # Physically combining both audio energies into a single 5-second chunk
    overlap_2 = t2_outro.overlay(t3_intro)
    
    # Final Track 2 = (Track 2, EXCLUDING its first 5s and last 5s) + (The baked 5s overlap)
    # Note: We drop t2[:fade_ms] because that audio was already played during Track 1's outro!
    out_2 = t2[fade_ms:-fade_ms] + overlap_2

    # =========================================================
    # Track 3 Processing (3_mix.mp3)
    # =========================================================
    # Final Track 3 = (Track 3, EXCLUDING its first 5s). No trailing overlap needed.
    out_3 = t3[fade_ms:]

    print("Exporting perfectly gapless mixed files to MP3...")
    out_1.export("1_mix.mp3", format="mp3")
    out_2.export("2_mix.mp3", format="mp3")
    out_3.export("3_mix.mp3", format="mp3")
    
    print("\nComplete! To test gapless sequential playback:")
    print("Run: mpv --gapless-audio=yes 1_mix.mp3 2_mix.mp3 3_mix.mp3")

if __name__ == "__main__":
    main()
