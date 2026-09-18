"""
Authentication management for YouTube Music (Automatic Browser Extraction, Browser Open, and Manual Headers).
"""
import json
import os
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from yt_dlp.cookies import extract_cookies_from_browser
import ytmusicapi
from ytmusicapi.auth.browser import initialize_headers

from ytstr.config import YTM_AUTH_FILE, ensure_config_dir

CANDIDATE_BROWSERS = [
    "chrome",
    "firefox",
    "brave",
    "edge",
    "chromium",
    "opera",
    "vivaldi",
]


class AuthManager:
    """Manages YouTube Music authentication credentials, browser extraction, and login flows."""

    def __init__(self, auth_path: Path = YTM_AUTH_FILE):
        self.auth_path = auth_path
        ensure_config_dir()

    def is_authenticated(self) -> bool:
        """Check if a valid auth file exists and contains session cookies."""
        if not self.auth_path.exists():
            return False
        try:
            with open(self.auth_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                cookie_str = data.get("cookie", "")
                return bool(
                    ("SAPISID" in cookie_str or "__Secure-3PAPISID" in cookie_str or "SID" in cookie_str)
                    or data.get("access_token")
                )
        except Exception:
            return False

    def get_auth_filepath(self) -> Optional[str]:
        """Return path string to auth file if authenticated, otherwise None."""
        if self.is_authenticated():
            return str(self.auth_path)
        return None

    def open_browser_for_login(self, url: str = "https://music.youtube.com") -> bool:
        """Open default system browser to YouTube Music login page."""
        try:
            return webbrowser.open(url, new=2)
        except Exception:
            return False

    def import_cookies_from_browser(self, browser_name: str = "auto") -> Tuple[bool, str]:
        """
        Automatically extract YouTube session cookies directly from installed browser
        without requiring manual developer tools or copy-pasting.

        Args:
            browser_name: 'auto', 'chrome', 'firefox', 'brave', 'edge', 'chromium', 'opera', 'vivaldi'

        Returns:
            Tuple[bool, str]: (Success, Message)
        """
        targets = (
            CANDIDATE_BROWSERS
            if browser_name.lower() == "auto"
            else [browser_name.lower()]
        )

        last_err = ""
        for b in targets:
            try:
                cookie_jar = extract_cookies_from_browser(b)
                if not cookie_jar:
                    continue

                yt_cookies: Dict[str, str] = {}
                for cookie in cookie_jar:
                    domain = getattr(cookie, "domain", "")
                    if "youtube.com" in domain or "google.com" in domain:
                        yt_cookies[cookie.name] = cookie.value

                # Verify critical authentication cookies exist
                has_auth = any(
                    k in yt_cookies
                    for k in ["SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID", "SID"]
                )

                if not has_auth:
                    last_err = f"No active YouTube session found in {b.capitalize()}. Please log in first."
                    continue

                # Build valid ytmusicapi browser headers dictionary
                cookie_str = "; ".join([f"{k}={v}" for k, v in yt_cookies.items()])
                base_headers = dict(initialize_headers())
                auth_data = {
                    **base_headers,
                    "cookie": cookie_str,
                    "x-goog-authuser": "0",
                    "authorization": "SAPISIDHASH dummy",
                }

                with open(self.auth_path, "w", encoding="utf-8") as f:
                    json.dump(auth_data, f, indent=4)

                return True, f"Successfully logged in from {b.capitalize()}!"

            except Exception as e:
                last_err = f"{b.capitalize()}: {e}"
                continue

        return False, last_err or "Could not extract cookies from any browser. Make sure you are logged into music.youtube.com."

    def save_headers(self, raw_headers: str) -> bool:
        """
        Parse raw request headers copied from browser developer tools
        and save as ytmusicapi auth json.
        """
        try:
            ytmusicapi.setup(filepath=str(self.auth_path), headers_raw=raw_headers)
            return self.is_authenticated()
        except Exception:
            return False

    def logout(self) -> bool:
        """Remove saved authentication credentials."""
        try:
            if self.auth_path.exists():
                self.auth_path.unlink()
            return True
        except Exception:
            return False
