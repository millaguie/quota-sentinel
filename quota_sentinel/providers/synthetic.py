"""Synthetic.new subscription quota provider.

Hits ``GET https://api.synthetic.new/v2/quotas`` with a Bearer token and
maps the response onto three sentinel windows:

- ``subscription``       — daily request budget (``subscription.{limit,requests}``)
- ``rolling_5h``         — rolling 5-hour request budget
                           (``rollingFiveHourLimit.{remaining,max}``)
- ``weekly_credits``     — weekly $ credits remaining
                           (``weeklyTokenLimit.percentRemaining``)

Tracking only ``subscription`` was a bug: the binding constraint is
usually the rolling 5-hour window (synthetic regenerates 5%/12 min after
heavy use), and the weekly $ limit is what catches a full-day spree.
With only the daily window, the sentinel reported 0% utilisation right
after midnight UTC even when the 5h window was at 84%.

``/quotas`` calls do not count against any of these windows, so polling
is safe.
"""

from __future__ import annotations

import urllib.error
from datetime import datetime, timezone

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_get

SYNTHETIC_QUOTAS_URL = "https://api.synthetic.new/v2/quotas"


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


class SyntheticUsageProvider(UsageProvider):
    """Synthetic — three concurrent request/credit budgets."""

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

        windows: dict[str, WindowUsage] = {}

        # ── subscription (daily) ────────────────────────────────────
        sub = data.get("subscription") or {}
        sub_limit = float(sub.get("limit") or 0)
        sub_requests = float(sub.get("requests") or 0)
        if sub_limit > 0:
            windows["subscription"] = WindowUsage(
                utilization=min(100.0, (sub_requests / sub_limit) * 100.0),
                resets_at=_parse_iso(sub.get("renewsAt") or sub.get("renews_at")),
                metadata={
                    "limit_requests": int(sub_limit),
                    "used_requests": int(sub_requests),
                    "remaining_requests": max(0, int(sub_limit - sub_requests)),
                },
            )

        # ── rolling 5-hour ──────────────────────────────────────────
        # synthetic returns ``remaining`` as an absolute count out of
        # ``max`` (NOT a percentage — the field name is misleading).
        # Utilisation = (max - remaining) / max * 100.
        # ``nextTickAt`` is when the next 5% drip lands; we expose it as
        # ``resets_at`` so the UI shows the next regeneration moment.
        # If the window is fully exhausted the real reset is ~5h after
        # last use, which the API does not surface; nextTickAt is the
        # closest approximation.
        rh = data.get("rollingFiveHourLimit") or {}
        rh_remaining = float(rh.get("remaining") or 0)
        rh_max = float(rh.get("max") or 0)
        if rh_max > 0:
            used = max(0.0, rh_max - rh_remaining)
            windows["rolling_5h"] = WindowUsage(
                utilization=min(100.0, (used / rh_max) * 100.0),
                resets_at=_parse_iso(rh.get("nextTickAt")),
                metadata={
                    "limit_requests": int(rh_max),
                    "used_requests": int(used),
                    "remaining_requests": max(0, int(rh_remaining)),
                    "regenerates_pct_per_tick": rh.get("tickPercent"),
                    "limited": bool(rh.get("limited") or False),
                },
            )

        # ── weekly $ credits ────────────────────────────────────────
        # ``percentRemaining`` is already a percentage (0–100).  The
        # API exposes ``maxCredits`` / ``remainingCredits`` as strings
        # like ``"$24.00"`` — we strip the prefix for metadata.
        wk = data.get("weeklyTokenLimit") or {}
        wk_pct = wk.get("percentRemaining")
        if isinstance(wk_pct, (int, float)):
            wk_pct_f = max(0.0, min(100.0, float(wk_pct)))
            # weekly limit doesn't expose a final reset timestamp; use
            # nextRegenAt + 1 tick if available so the UI shows
            # *something* meaningful for "when does this matter again".
            windows["weekly_credits"] = WindowUsage(
                utilization=100.0 - wk_pct_f,
                resets_at=_parse_iso(wk.get("nextRegenAt")),
                metadata={
                    "max_credits": str(wk.get("maxCredits") or "").lstrip("$"),
                    "remaining_credits": str(wk.get("remainingCredits") or "").lstrip(
                        "$"
                    ),
                    "next_regen_credits": str(wk.get("nextRegenCredits") or "").lstrip(
                        "$"
                    ),
                },
            )

        if not windows:
            return UsageResult(
                provider=self.name,
                error="no quota windows returned (free plan or new account?)",
            )

        return UsageResult(provider=self.name, windows=windows)
