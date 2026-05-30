"""Xiaomi MiMo Token Plan usage provider — session-cookie based.

Xiaomi's Token Plan (https://platform.xiaomimimo.com) ships dedicated
``tp-*`` API keys that work only for model calls against the OpenAI- or
Anthropic-compatible endpoints (e.g. ``https://token-plan-ams.xiaomimimo.com/v1``
for the Amsterdam/Europe cluster).  Those keys are rejected by the
quota/usage console endpoint, which is gated behind the operator's
browser session at ``platform.xiaomimimo.com``.

Until Xiaomi ships a first-class usage API, the only way to read live
plan / compensation / monthly token consumption is to hit the console
endpoint with the session cookie captured from a logged-in browser:

    GET https://platform.xiaomimimo.com/api/v1/tokenPlan/usage
    Cookie: <session cookie value>

Response shape (verified against ``kalcohol/opencode-statusline``,
``doc/provider-query-methods.md`` — the only third-party tracker that
documents the exact field names today)::

    {
      "code": 0,
      "data": {
        "usage": {
          "items": [
            {"name": "plan_total_token",         "used": ..., "limit": ..., "percent": ...},
            {"name": "compensation_total_token", "used": ..., "limit": ..., "percent": ...}
          ]
        },
        "monthUsage": {
          "items": [
            {"name": "month_total_token", "used": ..., "limit": ..., "percent": ...}
          ]
        }
      }
    }

The cluster (cn / sgp / ams) only matters for routing model traffic; the
usage console is the same single host for all regions, so the provider
takes a generic ``session_cookie`` and ignores the region.

Required ``provider_config``:

- ``session_cookie`` — value of the auth/session cookie issued by
  ``platform.xiaomimimo.com`` after login.  Refresh from DevTools when
  the meter starts reporting ``HTTP 401`` / ``HTTP 403``.

Optional:

- ``api_token`` — the ``tp-*`` Token Plan key.  Stored for
  fingerprinting / future PAYG hooks only; not used by ``fetch()``.
"""

from __future__ import annotations

import urllib.error
from typing import Any

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_get

USAGE_URL = "https://platform.xiaomimimo.com/api/v1/tokenPlan/usage"

# Maps the ``items[].name`` strings returned by the console to the
# sentinel window names.  Each console item carries used/limit/percent,
# so the mapping is 1:1 — no merging or arithmetic needed.
_ITEM_TO_WINDOW: dict[str, str] = {
    "plan_total_token": "plan",
    "compensation_total_token": "compensation",
    "month_total_token": "monthly",
}


def _clamp_pct(value: Any) -> float:
    try:
        pct = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, pct))


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _items_to_windows(
    items: list[dict[str, Any]], windows: dict[str, WindowUsage]
) -> None:
    """Project console items onto sentinel windows in-place."""
    for item in items or []:
        if not isinstance(item, dict):
            continue
        wname = _ITEM_TO_WINDOW.get(str(item.get("name") or ""))
        if not wname:
            continue
        used = _coerce_int(item.get("used"))
        limit = _coerce_int(item.get("limit"))
        # Prefer the server-computed percent when present; fall back to
        # used/limit so we still surface a window if Xiaomi ever drops
        # the convenience field.
        pct: float
        if "percent" in item and item.get("percent") is not None:
            pct = _clamp_pct(item.get("percent"))
        elif limit and limit > 0 and used is not None:
            pct = _clamp_pct(used / limit * 100.0)
        else:
            pct = 0.0
        metadata: dict[str, Any] = {"item_name": item.get("name")}
        if used is not None:
            metadata["used_tokens"] = used
        if limit is not None:
            metadata["limit_tokens"] = limit
        # Token Plan consoles do not expose a per-window reset timestamp
        # (subscription renewal is shown only on the dashboard, not via
        # this endpoint).  We surface utilisation now; the daemon's
        # velocity tracker derives the exhaustion ETA itself.
        windows[wname] = WindowUsage(
            utilization=pct,
            resets_at=None,
            metadata=metadata,
        )


class XiaomiTokenPlanUsageProvider(UsageProvider):
    """Xiaomi MiMo Token Plan — plan / compensation / monthly windows."""

    name = "xiaomi"

    def __init__(self, session_cookie: str = "", api_token: str = ""):
        self.session_cookie = session_cookie.strip()
        self.api_token = api_token  # unused for quota; kept for fingerprinting

    def merge_credentials_from(self, other):
        """Adopt ``other``'s session_cookie when our own is empty.

        Lets a desktop client that re-registers without a fresh browser
        cookie keep using the cookie a programmatic client already
        provided for the same ``tp-*`` fingerprint.
        """
        inherited = getattr(other, "session_cookie", "")
        if not self.session_cookie and inherited:
            self.session_cookie = inherited

    def _build_cookie_header(self) -> str:
        """Accept either ``name=value`` pairs or a bare value.

        Operators usually copy-paste the raw cookie value out of
        DevTools (no ``name=`` prefix).  The Token Plan console uses a
        small set of session cookies — to keep the contract simple we
        send whatever the operator pasted as-is when it already looks
        like a cookie header (contains ``=``), otherwise wrap it in
        ``session=<value>`` so the request is still well-formed.
        """
        cookie = self.session_cookie
        if "=" in cookie:
            return cookie
        return f"session={cookie}"

    def fetch(self) -> UsageResult:
        if not self.session_cookie:
            return UsageResult(provider=self.name, error="no session_cookie")

        try:
            data = http_get(
                USAGE_URL,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Cookie": self._build_cookie_header(),
                    "Referer": "https://platform.xiaomimimo.com/",
                },
            )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return UsageResult(
                    provider=self.name,
                    error=f"HTTP {e.code} — session cookie expired",
                )
            if e.code == 429:
                return UsageResult(provider=self.name, error="rate limited")
            return UsageResult(provider=self.name, error=f"HTTP {e.code}")
        except urllib.error.URLError as e:
            return UsageResult(provider=self.name, error=f"network error: {e.reason}")
        except Exception as e:  # noqa: BLE001
            return UsageResult(provider=self.name, error=f"unexpected error: {e}")

        if not isinstance(data, dict):
            return UsageResult(provider=self.name, error="malformed response")

        code = data.get("code")
        if code not in (0, None):
            msg = data.get("message") or data.get("msg") or f"code={code}"
            return UsageResult(provider=self.name, error=f"API: {msg}")

        payload = data.get("data") or {}
        if not isinstance(payload, dict):
            return UsageResult(provider=self.name, error="malformed data envelope")

        windows: dict[str, WindowUsage] = {}
        usage = payload.get("usage") or {}
        if isinstance(usage, dict):
            _items_to_windows(usage.get("items") or [], windows)
        month_usage = payload.get("monthUsage") or {}
        if isinstance(month_usage, dict):
            _items_to_windows(month_usage.get("items") or [], windows)

        if not windows:
            return UsageResult(
                provider=self.name,
                error="no usage windows in response (plan not active?)",
            )

        return UsageResult(provider=self.name, windows=windows)
