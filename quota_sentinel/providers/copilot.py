"""GitHub Copilot usage provider."""

from __future__ import annotations

import urllib.error
from datetime import UTC, datetime

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_get

COPILOT_PLAN_ALLOWANCES = {"free": 50, "pro": 300, "pro_plus": 1500}


class CopilotUsageProvider(UsageProvider):
    """Fetch premium request usage from GitHub billing API."""

    name = "copilot"

    def __init__(
        self,
        github_username: str,
        github_token: str,
        plan: str = "pro",
    ):
        self.username = github_username
        self.token = github_token
        if plan in COPILOT_PLAN_ALLOWANCES:
            self.allowance = COPILOT_PLAN_ALLOWANCES[plan]
        else:
            try:
                self.allowance = int(plan)
            except ValueError:
                self.allowance = 300

    def fetch(self) -> UsageResult:
        if not self.token:
            return UsageResult(provider=self.name, error="no token")
        if not self.username:
            return UsageResult(provider=self.name, error="no username")

        now = datetime.now(UTC)
        url = (
            f"https://api.github.com/users/{self.username}"
            f"/settings/billing/premium_request/usage"
            f"?year={now.year}&month={now.month}"
        )

        try:
            data = http_get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
            )
        except urllib.error.HTTPError as e:
            error_map = {401: "auth failed", 403: "no permission", 429: "rate limited"}
            return UsageResult(
                provider=self.name, error=error_map.get(e.code, f"HTTP {e.code}")
            )
        except Exception as e:
            return UsageResult(provider=self.name, error=str(e))

        total_used = sum(
            item.get("grossQuantity", 0) for item in data.get("usageItems", [])
        )
        utilization = (total_used / self.allowance * 100) if self.allowance > 0 else 0

        if now.month == 12:
            resets_at = datetime(now.year + 1, 1, 1, tzinfo=UTC)
        else:
            resets_at = datetime(now.year, now.month + 1, 1, tzinfo=UTC)

        return UsageResult(
            provider=self.name,
            windows={
                "monthly": WindowUsage(
                    utilization=min(utilization, 100), resets_at=resets_at
                )
            },
        )
