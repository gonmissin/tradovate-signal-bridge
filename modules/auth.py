import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from modules.console_theme import print_auth_payload
from modules.tradovate_selenium_login import api_v1_base_from_token_request_url, login_and_capture


def _parse_expiration_time(raw: Any) -> datetime | None:
    """Parse Tradovate ``expirationTime`` (usually ISO 8601) to UTC-aware datetime."""
    if raw is None or not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


class Auth:
    """
    Login matches enable.py: Selenium web trader + network capture of /auth/accesstokenrequest.

    Set ``TRADOVATE_SELENIUM_HEADED=1`` (or true/yes) to run Chrome with a visible window for debugging.
    ``device_id`` is accepted for API compatibility with callers but is not sent on the browser path.
    """

    def __init__(self):
        self.access_token: str | None = None
        self.base_url: str | None = None
        self.expiration_time: str | None = None
        self.expires_at: datetime | None = None
        self.last_auth_payload: dict[str, Any] | None = None

    def _login(self, username: str, password: str, device_id: str):
        _ = (device_id or "").strip() or str(uuid.uuid4())

        headed = os.environ.get("TRADOVATE_SELENIUM_HEADED", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        headless = not headed

        data, request_url = login_and_capture(username, password, headless=headless)

        print_auth_payload(dict(data))

        # Bearer first, then expiry metadata (same contract as before).
        token = data.get("accessToken")
        self.access_token = token.strip() if isinstance(token, str) else None
        if not self.access_token:
            raise RuntimeError("Login response missing accessToken")

        self.base_url = api_v1_base_from_token_request_url(request_url)

        et = data.get("expirationTime")
        self.expiration_time = et if isinstance(et, str) and et.strip() else None
        self.expires_at = _parse_expiration_time(self.expiration_time)
        self.last_auth_payload = dict(data)

        return self.access_token
