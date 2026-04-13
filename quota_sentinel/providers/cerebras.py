"""Cerebras usage provider."""

from __future__ import annotations


from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.errors import AuthError, RateLimitError, TransientError
from quota_sentinel.providers.http import http_get

CEREBRAS_USAGE_URL = "https://api.cerebras.ai/v1/usage"


class CerebrasUsageProvider(UsageProvider):
    """Cerebras — token-based quota with daily/weekly/monthly windows."""

    name = "cerebras"

    def __init__(self, api_token: str):
        self.api_token = api_token

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")

        try:
            data = http_get(
                CEREBRAS_USAGE_URL,
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

        # Daily quota
        daily_used = data.get("daily_tokens_used", 0)
        daily_limit = data.get("daily_tokens_limit", 0)
        if daily_limit > 0:
            pct = daily_used / daily_limit * 100
            windows["daily"] = WindowUsage(min(pct, 100.0))

        # Weekly quota
        weekly_used = data.get("weekly_tokens_used", 0)
        weekly_limit = data.get("weekly_tokens_limit", 0)
        if weekly_limit > 0:
            pct = weekly_used / weekly_limit * 100
            windows["weekly"] = WindowUsage(min(pct, 100.0))

        # Monthly quota
        monthly_used = data.get("monthly_tokens_used", 0)
        monthly_limit = data.get("monthly_tokens_limit", 0)
        if monthly_limit > 0:
            pct = monthly_used / monthly_limit * 100
            windows["monthly"] = WindowUsage(min(pct, 100.0))

        # Subscription quota (one-time allocation)
        subscription_used = data.get("subscription_tokens_used", 0)
        subscription_limit = data.get("subscription_tokens_limit", 0)
        if subscription_limit > 0:
            pct = subscription_used / subscription_limit * 100
            windows["subscription"] = WindowUsage(min(pct, 100.0))

        return UsageResult(provider=self.name, windows=windows)
