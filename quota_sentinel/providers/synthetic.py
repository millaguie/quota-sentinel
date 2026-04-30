"""Synthetic.new subscription quota provider.

Hits ``GET https://api.synthetic.new/v2/quotas`` with a Bearer token and
maps ``{subscription: {limit, requests, renewsAt}}`` onto a single
``subscription`` window so the sentinel UI/CLI render it next to the
other providers.

Synthetic exposes a request-count quota (not tokens), and ``/quotas``
calls do not themselves count against the limit, so polling is safe.
"""

from __future__ import annotations

import urllib.error
from datetime import datetime, timezone

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_get

SYNTHETIC_QUOTAS_URL = "https://api.synthetic.new/v2/quotas"


class SyntheticUsageProvider(UsageProvider):
    """Synthetic — request-count quota with a wall-clock reset."""

    name = "synthetic"

    def __init__(self, api_token: str):
        self.api_token = api_token

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")

        try:
            data = http_get(
                SYNTHETIC_QUOTAS_URL,
                headers={"Authorization": f"Bearer {self.api_token}"},
            )
        except urllib.error.HTTPError as e:
            error_map = {401: "auth failed", 429: "rate limited"}
            return UsageResult(
                provider=self.name, error=error_map.get(e.code, f"HTTP {e.code}")
            )
        except Exception as e:  # noqa: BLE001
            return UsageResult(provider=self.name, error=str(e))

        sub = data.get("subscription") or {}
        limit = float(sub.get("limit") or 0)
        requests = float(sub.get("requests") or 0)
        renews_at_raw = sub.get("renewsAt") or sub.get("renews_at")

        if limit <= 0:
            return UsageResult(
                provider=self.name,
                error="no subscription limit returned (not on a paid plan?)",
            )

        utilization = min(100.0, (requests / limit) * 100.0)

        resets_at: datetime | None = None
        if isinstance(renews_at_raw, str) and renews_at_raw:
            try:
                # Synthetic returns ISO-8601 with trailing Z; fromisoformat
                # 3.11+ accepts that, but defensively normalise.
                resets_at = datetime.fromisoformat(
                    renews_at_raw.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError:
                resets_at = None

        return UsageResult(
            provider=self.name,
            windows={
                "subscription": WindowUsage(
                    utilization=utilization,
                    resets_at=resets_at,
                    metadata={
                        "limit_requests": int(limit),
                        "used_requests": int(requests),
                        "remaining_requests": max(0, int(limit - requests)),
                    },
                )
            },
        )
