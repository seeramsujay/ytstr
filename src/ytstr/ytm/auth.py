"""
Authentication management for YouTube Music (Automatic Browser Extraction, Browser Open, and Manual Headers).
"""
import json
import os
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from yt_dlp.cookies import YDLLogger, _extract_firefox_cookies, extract_cookies_from_browser
import ytmusicapi
from ytmusicapi.auth.browser import initialize_headers

from ytstr.config import YTM_AUTH_FILE, ensure_config_dir

# Essential session & auth cookies for YouTube Music (prevents HTTP 413 Entity Too Large)
AUTH_COOKIE_KEYS = {
    "__Secure-3PAPISID",
    "__Secure-1PAPISID",
    "SAPISID",
    "__Secure-3PSID",
    "__Secure-1PSID",
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "LOGIN_INFO",
    "VISITOR_INFO1_LIVE",
    "PREF",
    "__Secure-3PSIDTS",
    "__Secure-1PSIDTS",
    "SIDCC",
    "__Secure-3PSIDCC",
    "__Secure-1PSIDCC",
}

# Custom profile roots for Firefox forks like Zen Browser, Floorp, LibreWolf, Waterfox
FIREFOX_FORKS: Dict[str, List[str]] = {
    "zen": [
        os.path.expanduser("~/.zen"),
        os.path.expanduser("~/.var/app/app.zen_browser.zen/.zen"),
        os.path.expanduser("~/.config/zen"),
    ],
    "librewolf": [
        os.path.expanduser("~/.librewolf"),
        os.path.expanduser("~/.var/app/io.gitlab.librewolf-community/.librewolf"),
    ],
    "floorp": [
        os.path.expanduser("~/.floorp"),
        os.path.expanduser("~/.var/app/one.ablaze.floorp/.floorp"),
    ],
    "waterfox": [
        os.path.expanduser("~/.waterfox"),
    ],
}

CANDIDATE_BROWSERS = [
    "zen",
    "firefox",
    "chrome",
    "brave",
    "edge",
    "chromium",
    "opera",
    "vivaldi",
    "librewolf",
    "floorp",
    "waterfox",
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
        (including Zen Browser, Firefox, Chrome, Brave, etc.) without requiring manual
        developer tools or copy-pasting.

        Args:
            browser_name: 'auto', 'zen', 'firefox', 'chrome', 'brave', 'edge', 'chromium', etc.

        Returns:
            Tuple[bool, str]: (Success, Message)
        """
        b_name = browser_name.lower().strip()
        targets = CANDIDATE_BROWSERS if b_name == "auto" else [b_name]

        last_err = ""
        for b in targets:
            try:
                cookie_jar = None

                # Check Firefox forks first (e.g. Zen Browser, LibreWolf, Floorp)
                if b in FIREFOX_FORKS:
                    for search_dir in FIREFOX_FORKS[b]:
                        if os.path.exists(search_dir):
                            try:
                                cookie_jar = _extract_firefox_cookies(search_dir, None, YDLLogger())
                                if cookie_jar and len(cookie_jar) > 0:
                                    break
                            except Exception:
                                pass
                else:
                    # Standard yt-dlp supported browser extraction
                    cookie_jar = extract_cookies_from_browser(b)

                if not cookie_jar:
                    continue

                yt_cookies: Dict[str, str] = {}
                # Two passes: first collect google.com, then overwrite with youtube.com
                # so specific YouTube session tokens (SID, SSID, HSID, SAPISID, etc.) always take precedence!
                for cookie in cookie_jar:
                    domain = getattr(cookie, "domain", "")
                    if "google.com" in domain and "youtube.com" not in domain:
                        if cookie.name in AUTH_COOKIE_KEYS:
                            yt_cookies[cookie.name] = cookie.value
                for cookie in cookie_jar:
                    domain = getattr(cookie, "domain", "")
                    if "youtube.com" in domain:
                        if cookie.name in AUTH_COOKIE_KEYS:
                            yt_cookies[cookie.name] = cookie.value

                # Verify critical authentication cookies exist
                has_auth = any(
                    k in yt_cookies
                    for k in ["__Secure-3PAPISID", "SAPISID", "__Secure-1PAPISID", "SID"]
                )

                if not has_auth:
                    last_err = f"No active YouTube session found in {b.capitalize()}."
                    continue

                # Build clean ytmusicapi browser headers dictionary
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

        if b_name == "auto":
            return (
                False,
                "No active YouTube session found across installed browsers (Zen, Firefox, Chrome, Brave, Edge, etc.). "
                "Please sign in to https://music.youtube.com in your browser, then re-run: ytstr --login",
            )
        return False, last_err or f"Could not extract cookies from {browser_name.capitalize()}."

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
