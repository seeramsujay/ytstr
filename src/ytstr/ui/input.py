"""
Terminal TTY raw keyboard listener and global media-key interception.
"""
import select
import sys
import termios
import time
import tty
from typing import Any, Callable, Optional

try:
    from pynput import keyboard
except ImportError:
    keyboard = None


class KeyboardListener:
    """Listens for terminal keypresses and hardware media keys."""

    def __init__(
        self,
        on_toggle_pause: Callable[[], None],
        on_next: Callable[[], None],
        on_prev: Callable[[], None],
        on_volume_up: Callable[[], None],
        on_volume_down: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self.on_toggle_pause = on_toggle_pause
        self.on_next = on_next
        self.on_prev = on_prev
        self.on_volume_up = on_volume_up
        self.on_volume_down = on_volume_down
        self.on_quit = on_quit

        self._running = True

    def start(self):
        """Start listening for key events."""
        if keyboard is not None:
            self._start_global_listener()

        self._run_tty_loop()

    def _start_global_listener(self):
        def on_press(key: Any):
            if not self._running:
                return False
            try:
                if key in (keyboard.Key.media_play_pause, keyboard.Key.f8):
                    self.on_toggle_pause()
                elif key in (keyboard.Key.media_next, keyboard.Key.f9):
                    self.on_next()
                elif key in (keyboard.Key.media_previous, keyboard.Key.f7):
                    self.on_prev()
            except Exception:
                pass

        try:
            listener = keyboard.Listener(on_press=on_press)
            listener.daemon = True
            listener.start()
        except Exception:
            pass

    def _run_tty_loop(self):
        if not sys.stdin.isatty():
            while self._running:
                time.sleep(0.5)
            return

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while self._running:
                r, _, _ = select.select([sys.stdin], [], [], 0.3)
                if r:
                    ch = sys.stdin.read(1)
                    if ch == " ":
                        self.on_toggle_pause()
                    elif ch in (">", ".", "n"):
                        self.on_next()
                    elif ch in ("<", ",", "p"):
                        self.on_prev()
                    elif ch in ("9", "-"):
                        self.on_volume_down()
                    elif ch in ("0", "+", "="):
                        self.on_volume_up()
                    elif ch in ("q", "Q"):
                        self._running = False
                        self.on_quit()
                        break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def stop(self):
        self._running = False
