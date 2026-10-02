"""
Authentication management for YouTube Music (Automatic Browser Extraction, Browser Open, and Manual Headers).
"""
import json
import os
import platform
import subprocess
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
# (Linux, Flatpak, and macOS profile locations — macOS stores profiles under
# ~/Library/Application Support/<browser>)
FIREFOX_FORKS: Dict[str, List[str]] = {
    "zen": [
        os.path.expanduser("~/.zen"),
        os.path.expanduser("~/.var/app/app.zen_browser.zen/.zen"),
        os.path.expanduser("~/.config/zen"),
        os.path.expanduser("~/Library/Application Support/zen"),
        os.path.expanduser("~/Library/Application Support/Zen Browser"),
        os.path.expanduser("~/Library/Application Support/Zen"),
    ],
    "librewolf": [
        os.path.expanduser("~/.librewolf"),
        os.path.expanduser("~/.var/app/io.gitlab.librewolf-community/.librewolf"),
        os.path.expanduser("~/Library/Application Support/LibreWolf"),
    ],
    "floorp": [
        os.path.expanduser("~/.floorp"),
        os.path.expanduser("~/.var/app/one.ablaze.floorp/.floorp"),
        os.path.expanduser("~/Library/Application Support/Floorp"),
    ],
    "waterfox": [
        os.path.expanduser("~/.waterfox"),
        os.path.expanduser("~/Library/Application Support/Waterfox"),
    ],
}

CANDIDATE_BROWSERS = [
    "zen",
    "firefox",
    "chrome",
    "brave",
    "safari",
    "edge",
    "chromium",
    "opera",
    "vivaldi",
    "librewolf",
    "floorp",
    "waterfox",
]

# Native macOS application bundle names for browsers
MACOS_BROWSER_APPS: Dict[str, List[str]] = {
    "zen": ["Zen", "Zen Browser"],
    "safari": ["Safari"],
    "chrome": ["Google Chrome"],
    "firefox": ["Firefox"],
    "brave": ["Brave Browser"],
    "edge": ["Microsoft Edge"],
    "arc": ["Arc"],
    "opera": ["Opera"],
    "vivaldi": ["Vivaldi"],
    "librewolf": ["LibreWolf"],
    "floorp": ["Floorp"],
    "waterfox": ["Waterfox"],
}


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

    def open_browser_for_login(
        self,
        browser_name: str = "auto",
        url: str = "https://music.youtube.com",
    ) -> bool:
        """
        Open specified or default system browser to YouTube Music login page.
        Supports native macOS app launching ('open -a <app> <url>'), Linux desktop tools,
        and stdlib webbrowser fallback.
        """
        # Support argument order flexibility: open_browser_for_login(url) or open_browser_for_login(browser, url)
        if browser_name.startswith("http://") or browser_name.startswith("https://"):
            url, browser_name = browser_name, "auto"

        b_key = browser_name.lower().strip()

        # macOS native app opening
        if platform.system() == "Darwin":
            if b_key in MACOS_BROWSER_APPS:
                for app_name in MACOS_BROWSER_APPS[b_key]:
                    try:
                        res = subprocess.run(
                            ["open", "-a", app_name, url],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        if res.returncode == 0:
                            return True
                    except Exception:
                        pass

            # Fallback to default browser on macOS
            try:
                res = subprocess.run(
                    ["open", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if res.returncode == 0:
                    return True
            except Exception:
                pass

        # Linux direct binary or xdg-open
        if platform.system() == "Linux" and b_key != "auto":
            try:
                subprocess.Popen([b_key, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                pass

        # Standard library webbrowser fallback
        try:
            if b_key != "auto":
                try:
                    controller = webbrowser.get(b_key)
                    if controller.open(url, new=2):
                        return True
                except Exception:
                    pass
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

            except PermissionError as pe:
                if b == "safari":
                    last_err = (
                        "Safari: Access to Safari cookies requires Full Disk Access on macOS. "
                        "Go to System Settings > Privacy & Security > Full Disk Access and add your terminal application."
                    )
                else:
                    last_err = f"{b.capitalize()}: {pe}"
                continue
            except Exception as e:
                last_err = f"{b.capitalize()}: {e}"
                continue

        if b_name == "auto":
            return (
                False,
                "No active YouTube session found across installed browsers (Zen, Safari, Firefox, Chrome, Brave, Edge, etc.). "
                "Please sign in to https://music.youtube.com in your browser, then re-run: ytstr --login",
            )
        return False, last_err or f"Could not extract cookies from {browser_name.capitalize()}."

    def login_from_zen(self) -> bool:
        """Compatibility wrapper: import session cookies from Zen Browser."""
        ok, _ = self.import_cookies_from_browser("zen")
        return ok

    def login_from_browser(self, browser_name: str = "auto") -> bool:
        """Compatibility wrapper: import session cookies from specified browser."""
        ok, _ = self.import_cookies_from_browser(browser_name)
        return ok

    def setup_from_browser(self, browser_name: str = "auto") -> bool:
        """
        Convenience method returning boolean status indicating whether browser
        cookie extraction and auth file initialization succeeded.
        """
        ok, _ = self.import_cookies_from_browser(browser_name)
        return ok

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
