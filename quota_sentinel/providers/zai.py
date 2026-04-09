"""Z.ai (Zhipu GLM) usage provider."""

from __future__ import annotations

import urllib.error
from datetime import UTC, datetime

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_get

ZAI_QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"

_ZAI_UNIT_MAP = {3: "hours", 5: "mcp", 6: "days"}


class ZaiUsageProvider(UsageProvider):
    """Fetch quota usage from Z.ai API."""

    name = "zai"

    def __init__(self, api_token: str):
        self.api_token = api_token

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")

        try:
            data = http_get(
                ZAI_QUOTA_URL, headers={"Authorization": f"Bearer {self.api_token}"}
            )
        except urllib.error.HTTPError as e:
            error_map = {401: "auth failed", 429: "rate limited"}
            return UsageResult(
                provider=self.name, error=error_map.get(e.code, f"HTTP {e.code}")
            )
        except Exception as e:
            return UsageResult(provider=self.name, error=str(e))

        if not data.get("success"):
            return UsageResult(provider=self.name, error="API returned success=false")

        windows: dict[str, WindowUsage] = {}
        for limit in data.get("data", {}).get("limits", []):
            if limit.get("type") != "TOKENS_LIMIT":
                continue
            unit = limit.get("unit", 0)
            number = limit.get("number", "?")
            unit_name = _ZAI_UNIT_MAP.get(unit, f"u{unit}")
            window_name = f"{number}{unit_name}"

            resets_at = None
            reset_ms = limit.get("nextResetTime")
            if reset_ms:
                try:
                    resets_at = datetime.fromtimestamp(reset_ms / 1000, tz=UTC)
                except (ValueError, OSError):
                    pass

            windows[window_name] = WindowUsage(
                utilization=float(limit.get("percentage", 0) or 0),
                resets_at=resets_at,
            )

        return UsageResult(provider=self.name, windows=windows)
