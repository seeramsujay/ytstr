"""
Authentication management for YouTube Music (Browser Cookies and OAuth).
"""
import json
import os
from pathlib import Path
from typing import Optional, Tuple
import ytmusicapi

from ytstr.config import YTM_AUTH_FILE, ensure_config_dir


class AuthManager:
    """Manages YouTube Music authentication credentials and login flows."""

    def __init__(self, auth_path: Path = YTM_AUTH_FILE):
        self.auth_path = auth_path
        ensure_config_dir()

    def is_authenticated(self) -> bool:
        """Check if a valid auth file exists."""
        if not self.auth_path.exists():
            return False
        try:
            with open(self.auth_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Check for either OAuth structure or browser header structure
                return bool(
                    data.get("cookie")
                    or data.get("access_token")
                    or "User-Agent" in data
                    or "authorization" in data
                )
        except Exception:
            return False

    def get_auth_filepath(self) -> Optional[str]:
        """Return path string to auth file if authenticated, otherwise None."""
        if self.is_authenticated():
            return str(self.auth_path)
        return None

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

    def save_oauth_credentials(self, client_id: str, client_secret: str) -> Tuple[bool, str]:
        """
        Execute OAuth device code setup for YouTube Music.
        Returns (success, message).
        """
        try:
            token = ytmusicapi.setup_oauth(
                client_id=client_id,
                client_secret=client_secret,
                filepath=str(self.auth_path),
                open_browser=True,
            )
            if token and self.auth_path.exists():
                return True, "OAuth authentication successful!"
            return False, "OAuth setup did not return a valid token."
        except Exception as e:
            return False, f"OAuth error: {e}"

    def logout(self) -> bool:
        """Remove saved authentication credentials."""
        try:
            if self.auth_path.exists():
                self.auth_path.unlink()
            return True
        except Exception:
            return False
