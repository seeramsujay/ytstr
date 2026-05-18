import subprocess
import time

def stream_to_mpv():
    # Generate 5 seconds of 440hz sine wave raw PCM using ffmpeg
    cmd1 = ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-f", "s16le", "-ar", "44100", "-ac", "2", "-"]
    p1 = subprocess.Popen(cmd1, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    pcm_data = p1.stdout.read()
    
    mpv_cmd = [
        "mpv", "-", 
        "--no-video",
        "--demuxer=rawaudio", 
        "--demuxer-rawaudio-channels=2", 
        "--demuxer-rawaudio-rate=44100", 
        "--demuxer-rawaudio-format=s16le"
    ]
    p2 = subprocess.Popen(mpv_cmd, stdin=subprocess.PIPE)
    
    # Write in chunks
    chunk_size = 176400 # 1 second
    for i in range(0, len(pcm_data), chunk_size):
        chunk = pcm_data[i:i+chunk_size]
        p2.stdin.write(chunk)
        p2.stdin.flush()
        print(f"Wrote {len(chunk)} bytes")
        time.sleep(0.5) # Feed faster than realtime
    
    p2.stdin.close()
    p2.wait()

stream_to_mpv()
