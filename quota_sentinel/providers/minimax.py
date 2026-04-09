"""MiniMax coding plan usage provider."""

from __future__ import annotations

import time
import urllib.error
from datetime import UTC, datetime

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_get

MINIMAX_REMAINS_URL = (
    "https://platform.minimax.io/v1/api/openplatform/coding_plan/remains"
)


class MiniMaxUsageProvider(UsageProvider):
    """MiniMax coding plan — per-model interval + weekly quotas."""

    name = "minimax"

    def __init__(self, api_token: str, group_id: str):
        self.api_token = api_token
        self.group_id = group_id

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")
        if not self.group_id:
            return UsageResult(provider=self.name, error="no group_id")

        url = f"{MINIMAX_REMAINS_URL}?GroupId={self.group_id}"
        try:
            data = http_get(
                url,
                headers={
                    "accept": "application/json, text/plain, */*",
                    "authorization": f"Bearer {self.api_token}",
                    "referer": "https://platform.minimax.io/user-center/payment/coding-plan",
                },
            )
        except urllib.error.HTTPError as e:
            error_map = {401: "auth failed", 429: "rate limited"}
            return UsageResult(
                provider=self.name, error=error_map.get(e.code, f"HTTP {e.code}")
            )
        except Exception as e:
            return UsageResult(provider=self.name, error=str(e))

        status_code = data.get("base_resp", {}).get("status_code", -1)
        if status_code != 0:
            msg = data.get("base_resp", {}).get("status_msg", "unknown")
            return UsageResult(provider=self.name, error=f"API: {msg}")

        windows: dict[str, WindowUsage] = {}
        for model in data.get("model_remains", []):
            mname = model.get("model_name", "?")
            lower = mname.lower()
            if any(
                kw in lower
                for kw in (
                    "hailuo",
                    "speech",
                    "music",
                    "image",
                    "video",
                    "audio",
                )
            ):
                continue
            short = mname.replace("MiniMax-", "MM-").replace("minimax-", "mm-")

            # Interval quota
            total = model.get("current_interval_total_count", 0)
            remaining = model.get("current_interval_usage_count", 0)
            if total > 0:
                used = total - remaining
                pct = used / total * 100
                ra = self._reset_time(model.get("remains_time", 0))
                windows[f"{short}_interval"] = WindowUsage(min(pct, 100), ra)

            # Weekly quota
            wtotal = model.get("current_weekly_total_count", 0)
            if wtotal > 0:
                wremaining = model.get("current_weekly_usage_count", 0)
                wused = wtotal - wremaining
                wpct = wused / wtotal * 100
                wra = self._reset_time(model.get("weekly_remains_time", 0))
                windows[f"{short}_weekly"] = WindowUsage(min(wpct, 100), wra)

        return UsageResult(provider=self.name, windows=windows)

    @staticmethod
    def _reset_time(remains_ms: int) -> datetime | None:
        if remains_ms <= 0:
            return None
        return datetime.fromtimestamp(time.time() + remains_ms / 1000, tz=UTC)
