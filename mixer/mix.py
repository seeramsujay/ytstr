#!/usr/bin/env python3
import sys
import os
try:
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence
except ImportError:
    print("Please run: pip install pydub")
    sys.exit(1)

def trim_silence(audio, silence_threshold=-50.0, chunk_size=10):
    start_trim = detect_leading_silence(audio, silence_threshold=silence_threshold, chunk_size=chunk_size)
    trimmed_start = audio[start_trim:]
    
    end_trim = detect_leading_silence(trimmed_start.reverse(), silence_threshold=silence_threshold, chunk_size=chunk_size)
    if end_trim > 0:
        return trimmed_start[:-end_trim]
    return trimmed_start

def mix_songs():
    fade_ms = 5000
    
    # Load the user's 3 songs
    print("Loading 1...")
    try:
        s1 = AudioSegment.from_file("1.mp3") 
    except Exception:
        # Fallback to general finding just in case they used different extensions
        files = sorted([f for f in os.listdir('.') if f.startswith('1.')])
        if files: s1 = AudioSegment.from_file(files[0])
        else: sys.exit("Missing 1")
        
    print("Loading 2...")
    try:
        s2 = AudioSegment.from_file("2.mp3") 
    except Exception:
        files = sorted([f for f in os.listdir('.') if f.startswith('2.')])
        if files: s2 = AudioSegment.from_file(files[0])
        else: sys.exit("Missing 2")
        
    print("Loading 3...")
    try:
        s3 = AudioSegment.from_file("3.mp3")
    except Exception:
        files = sorted([f for f in os.listdir('.') if f.startswith('3.')])
        if files: s3 = AudioSegment.from_file(files[0])
        else: sys.exit("Missing 3")

    print(f"Trimming silent intros and outros (Spotify Automix technique)...")
    s1 = trim_silence(s1)
    s2 = trim_silence(s2)
    s3 = trim_silence(s3)

    print(f"Mixing overlapping fade for {fade_ms}ms...")

    # For 1 to 2
    fout_1 = s1[-fade_ms:].fade_out(fade_ms)
    fin_2 = s2[:fade_ms].fade_in(fade_ms)
    overlap_1_2 = fout_1.overlay(fin_2)
    
    # 01_mix.mp3 consists of the full Song 1 up to the last 5 seconds + the 5 second overlap.
    out_1 = s1[:-fade_ms] + overlap_1_2

    # For 2 to 3
    # Wait, the start of 2 was already consumed in 01_mix.mp3 !
    # So for 02_mix.mp3, we only need the middle of 2 + the end overlap of 2 and 3!
    fout_2 = s2[-fade_ms:].fade_out(fade_ms)
    fin_3 = s3[:fade_ms].fade_in(fade_ms)
    overlap_2_3 = fout_2.overlay(fin_3)
    
    # 02_mix.mp3 consists of Song 2 starting from 5s up to its last 5s, + the new overlap
    out_2 = s2[fade_ms:-fade_ms] + overlap_2_3
    
    # 03_mix.mp3 consists of whatever is left of Song 3 (from 5s to the end)
    out_3 = s3[fade_ms:]

    print("Exporting mixed files...")
    out_1.export("01_mix.mp3", format="mp3")
    out_2.export("02_mix.mp3", format="mp3")
    out_3.export("03_mix.mp3", format="mp3")
    
    print("\nDone! Run 'mpv --gapless-audio=yes 0*_mix.mp3' to hear it seamlessly crossfade between discrete files!")

if __name__ == "__main__":
    mix_songs()
