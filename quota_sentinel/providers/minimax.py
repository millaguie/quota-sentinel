"""MiniMax coding plan usage provider.

As of early 2026 the Token/Coding Plan usage endpoint
(``/v1/api/openplatform/coding_plan/remains``) no longer accepts the
``sk-cp-*`` API key on its own.  Calling it with only
``Authorization: Bearer <key>`` now comes back with::

    {"base_resp": {"status_code": 1004, "status_msg": "cookie is missing, log in again"}}

The endpoint is gated behind the operator's logged-in browser session at
``platform.minimax.io`` — exactly like the Xiaomi Token Plan console.  So
the provider takes a ``session_cookie`` captured from a logged-in browser
and sends it alongside the Bearer header.  Refresh the cookie from DevTools
when the meter starts reporting ``cookie is missing`` / ``HTTP 401``.

(See https://github.com/MiniMax-AI/MiniMax-M2/issues/88.)
"""

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

    def __init__(self, api_token: str, group_id: str, session_cookie: str = ""):
        self.api_token = api_token
        self.group_id = group_id
        self.session_cookie = session_cookie.strip()

    def merge_credentials_from(self, other) -> None:
        """Adopt ``other``'s session_cookie when our own is empty.

        Lets a desktop client (Stream Deck) that re-registers without a
        fresh browser cookie keep using the cookie a programmatic client
        already provided for the same ``sk-cp-*`` fingerprint.
        """
        inherited = getattr(other, "session_cookie", "")
        if not self.session_cookie and inherited:
            self.session_cookie = inherited

    def _build_cookie_header(self) -> str:
        """Accept either ``name=value`` pairs or a bare value.

        Operators usually copy-paste the raw session cookie value out of
        DevTools (no ``name=`` prefix).  When the pasted value already
        looks like a cookie header (contains ``=``) we send it as-is;
        otherwise we wrap it in ``session=<value>`` so the request stays
        well-formed.
        """
        cookie = self.session_cookie
        if "=" in cookie:
            return cookie
        return f"session={cookie}"

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")
        if not self.group_id:
            return UsageResult(provider=self.name, error="no group_id")
        if not self.session_cookie:
            return UsageResult(provider=self.name, error="no session_cookie")

        url = f"{MINIMAX_REMAINS_URL}?GroupId={self.group_id}"
        try:
            data = http_get(
                url,
                headers={
                    "accept": "application/json, text/plain, */*",
                    "authorization": f"Bearer {self.api_token}",
                    "cookie": self._build_cookie_header(),
                    "referer": "https://platform.minimax.io/user-center/payment/coding-plan",
                },
            )
        except urllib.error.HTTPError as e:
            error_map = {
                401: "session cookie expired",
                403: "session cookie expired",
                429: "rate limited",
            }
            return UsageResult(
                provider=self.name, error=error_map.get(e.code, f"HTTP {e.code}")
            )
        except Exception as e:
            return UsageResult(provider=self.name, error=str(e))

        status_code = data.get("base_resp", {}).get("status_code", -1)
        if status_code != 0:
            msg = data.get("base_resp", {}).get("status_msg", "unknown")
            # 1004 == "cookie is missing, log in again" — the session
            # cookie went stale; surface it the same way as an HTTP 401 so
            # the operator knows to refresh the cookie rather than the key.
            if status_code == 1004 or "cookie" in msg.lower():
                return UsageResult(provider=self.name, error="session cookie expired")
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
