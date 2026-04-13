"""OpenAI usage provider."""

from __future__ import annotations


from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.errors import AuthError, RateLimitError, TransientError
from quota_sentinel.providers.http import http_get

OPENAI_USAGE_URL = "https://api.openai.com/v1/usage"


class OpenAIUsageProvider(UsageProvider):
    """OpenAI — subscription/usage-based quota tracking."""

    name = "openai"

    def __init__(self, api_token: str):
        self.api_token = api_token

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")

        try:
            data = http_get(
                OPENAI_USAGE_URL,
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

        # Subscription quota
        subscription_limit = data.get("subscription_total", 0)
        subscription_used = data.get("subscription_used", 0)
        if subscription_limit > 0:
            pct = subscription_used / subscription_limit * 100
            windows["subscription"] = WindowUsage(min(pct, 100.0))

        # Usage-based quotas (if present)
        usage_total = data.get("usage_total", 0)
        usage_used = data.get("usage_used", 0)
        if usage_total > 0:
            pct = usage_used / usage_total * 100
            windows["usage"] = WindowUsage(min(pct, 100.0))

        # Overage flag
        if data.get("has_any_overage", False):
            windows["overage"] = WindowUsage(100.0)

        return UsageResult(provider=self.name, windows=windows)
