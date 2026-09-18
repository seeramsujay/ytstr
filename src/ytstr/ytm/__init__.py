"""
YouTube Music integration, authentication, and lightweight GUI.
"""
from ytstr.ytm.auth import AuthManager
from ytstr.ytm.client import YouTubeMusicClient
from ytstr.ytm.gui import YTMDesktopApp, main as gui_main

__all__ = ["AuthManager", "YouTubeMusicClient", "YTMDesktopApp", "gui_main"]
