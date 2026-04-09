"""Claude Code (Anthropic OAuth) usage provider."""

from __future__ import annotations

import logging
import time
import urllib.error
from datetime import datetime

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_get, http_post_json

logger = logging.getLogger(__name__)

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_TOKEN_REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
CLAUDE_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


class ClaudeUsageProvider(UsageProvider):
    """Fetch usage from Anthropic OAuth API.

    Tokens are provided directly — no filesystem access.
    The provider refreshes the access token automatically and exposes
    the updated credentials via .current_credentials() so the store
    can propagate them to other subscribers of the same key.
    """

    name = "claude"

    def __init__(
        self,
        access_token: str,
        refresh_token: str = "",
        expires_at: int | float = 0,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at  # ms since epoch

    def current_credentials(self) -> dict:
        """Return current token state (may have been refreshed)."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    def fetch(self) -> UsageResult:
        if not self.access_token:
            return UsageResult(provider=self.name, error="no credentials")

        if self._is_expired():
            if not self._refresh():
                return UsageResult(provider=self.name, error="token refresh failed")

        try:
            data = http_get(CLAUDE_USAGE_URL, headers={
                "Authorization": f"Bearer {self.access_token}",
                "anthropic-beta": "oauth-2025-04-20",
            })
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return UsageResult(provider=self.name, error="rate limited")
            return UsageResult(provider=self.name, error=f"HTTP {e.code}")
        except Exception as e:
            return UsageResult(provider=self.name, error=str(e))

        windows: dict[str, WindowUsage] = {}
        for key in ("five_hour", "seven_day", "seven_day_sonnet", "seven_day_opus"):
            bucket = data.get(key, {})
            if bucket:
                resets_at = None
                if bucket.get("resets_at"):
                    try:
                        resets_at = datetime.fromisoformat(bucket["resets_at"])
                    except (ValueError, TypeError):
                        pass
                windows[key] = WindowUsage(
                    utilization=float(bucket.get("utilization", 0) or 0),
                    resets_at=resets_at,
                )

        return UsageResult(provider=self.name, windows=windows)

    def _is_expired(self) -> bool:
        return time.time() * 1000 >= self.expires_at

    def _refresh(self) -> bool:
        if not self.refresh_token:
            return False
        try:
            data = http_post_json(CLAUDE_TOKEN_REFRESH_URL, {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": CLAUDE_OAUTH_CLIENT_ID,
            })
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]
            self.expires_at = int(time.time() * 1000) + data.get("expires_in", 3600) * 1000
            logger.info("Claude OAuth token refreshed")
            return True
        except Exception as e:
            logger.error("Claude token refresh failed: %s", e)
            return False
