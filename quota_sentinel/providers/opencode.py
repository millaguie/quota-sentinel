"""OpenCode free-tier usage provider.

Tracks usage of free models like minimax-m2.5-free, qwen3.6-plus-free
provided through OpenCode's unified API.
"""

from __future__ import annotations


from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.errors import AuthError, RateLimitError, TransientError
from quota_sentinel.providers.http import http_get

OPENCODE_FREE_URL = "https://opencode.ai/api/v1/free/usage"


class OpenCodeUsageProvider(UsageProvider):
    """OpenCode free-tier models — daily/weekly quotas.

    For free models like minimax-m2.5-free, qwen3.6-plus-free.
    These have separate quotas from paid plans.
    """

    name = "opencode"

    def __init__(self, api_token: str):
        self.api_token = api_token

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")

        try:
            data = http_get(
                OPENCODE_FREE_URL,
                headers={"Authorization": f"Bearer {self.api_token}"},
            )
        except AuthError as e:
            return UsageResult(provider=self.name, error=str(e))
        except RateLimitError as e:
            return UsageResult(provider=self.name, error=str(e))
        except TransientError as e:
            return UsageResult(provider=self.name, error=str(e))
        except Exception as e:
            return UsageResult(provider=self.name, error=f"unexpected error: {e}")

        windows: dict[str, WindowUsage] = {}

        # Daily free quota
        daily_used = data.get("daily_free_used", 0)
        daily_limit = data.get("daily_free_limit", 0)
        if daily_limit > 0:
            pct = daily_used / daily_limit * 100
            windows["daily_free"] = WindowUsage(min(pct, 100.0))

        # Weekly free quota
        weekly_used = data.get("weekly_free_used", 0)
        weekly_limit = data.get("weekly_free_limit", 0)
        if weekly_limit > 0:
            pct = weekly_used / weekly_limit * 100
            windows["weekly_free"] = WindowUsage(min(pct, 100.0))

        # Monthly free quota
        monthly_used = data.get("monthly_free_used", 0)
        monthly_limit = data.get("monthly_free_limit", 0)
        if monthly_limit > 0:
            pct = monthly_used / monthly_limit * 100
            windows["monthly_free"] = WindowUsage(min(pct, 100.0))

        return UsageResult(provider=self.name, windows=windows)
