import mpv
import sys
import time

player = mpv.MPV(ytdl=True, video=False, terminal='no', log_handler=print)

fade_opts = "silenceremove=start_periods=1:start_threshold=-50dB"
player.af = fade_opts

player.play('https://www.youtube.com/watch?v=DkgNWHeo5ZI')
time.sleep(10)
player.terminate()
