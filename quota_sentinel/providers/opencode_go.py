"""OpenCode Go usage provider — session-cookie based (no public quota API).

OpenCode's `Go` subscription plan (https://opencode.ai/docs/go/) does NOT
expose a programmatic usage endpoint — the open feature request
(https://github.com/anomalyco/opencode/issues/10448 for Zen balance,
https://github.com/anomalyco/opencode/issues/18648 for Go/Zen usage) is
still open.

The dashboard markup changed in 2026-10 when the console moved to a
SolidJS SPA (no SSR hydration payload any more), so scraping is only the
fallback.  The primary path hits the same JSON endpoint the Console UI
uses:

    GET https://opencode.ai/console/api/go/status
    Authorization: Bearer <__Host-console_session cookie>
    x-org-id: <workspace_id>

which returns ``access.meters.{fiveHour,week,month}`` with exact
``limitMicroCents``/``usedMicroCents`` and ``resetsAt`` timestamps.

Required ``provider_config`` (passed via the sentinel registration
payload, merged on top of the bare API key):

- ``workspace_id`` — UUID of the user's OpenCode workspace (from the URL
  bar after logging in at ``opencode.ai``, or from
  ``GET /console/api/orgs`` with the session token).  Doubles as the
  ``x-org-id`` header value.
- ``session_cookie`` — value of the ``__Host-console_session`` cookie
  (DevTools → Application → Cookies → opencode.ai).  Refresh when calls
  start returning HTTP 401.
- ``auth_cookie`` — legacy SSR scrape fallback; no longer required when a
  session cookie is present.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage

DASHBOARD_URL_PREFIX = "https://opencode.ai/workspace/"
DASHBOARD_URL_SUFFIX = "/go"

CONSOLE_STATUS_URL = "https://opencode.ai/console/api/go/status"

# Console meter key -> sentinel window name.
_METER_WINDOWS = {"fiveHour": "rolling_5h", "week": "weekly", "month": "monthly"}

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# SolidJS SSR hydration emits each window as
#   <key>:$R[<n>]={...usagePercent:<num>,...resetInSec:<num>,...}
# field order varies, so each window has two regexes (pct-first / reset-first).
_NUM = r"(-?\d+(?:\.\d+)?)"


def _make_window_patterns(key: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    pct_first = re.compile(
        rf"{key}:\$R\[\d+\]=\{{[^}}]*usagePercent:{_NUM}[^}}]*resetInSec:{_NUM}[^}}]*\}}"
    )
    reset_first = re.compile(
        rf"{key}:\$R\[\d+\]=\{{[^}}]*resetInSec:{_NUM}[^}}]*usagePercent:{_NUM}[^}}]*\}}"
    )
    return pct_first, reset_first


_WINDOW_KEYS: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "rolling_5h": _make_window_patterns("rollingUsage"),
    "weekly": _make_window_patterns("weeklyUsage"),
    "monthly": _make_window_patterns("monthlyUsage"),
}


def _parse_window(
    html: str, patterns: tuple[re.Pattern[str], re.Pattern[str]]
) -> tuple[float, float] | None:
    """Return (usagePercent, resetInSec) or None if not found / malformed."""
    pct_first, reset_first = patterns
    m = pct_first.search(html)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except (TypeError, ValueError):
            pass
    m = reset_first.search(html)
    if m:
        try:
            return float(m.group(2)), float(m.group(1))
        except (TypeError, ValueError):
            pass
    return None


class OpencodeGoUsageProvider(UsageProvider):
    """OpenCode Go — three rolling-budget windows scraped from the dashboard."""

    name = "opencode_go"

    def __init__(
        self,
        workspace_id: str = "",
        auth_cookie: str = "",
        api_token: str = "",
        session_cookie: str = "",
    ):
        self.workspace_id = workspace_id.strip()
        self.auth_cookie = auth_cookie.strip()
        self.session_cookie = (session_cookie or "").strip()
        # Bearer key is kept for fingerprinting/registration only; the
        # ``/zen/go/v1`` API has no usage endpoint, so we never use it.
        self.api_token = api_token

    def merge_credentials_from(self, other):
        """Adopt ``other``'s auth_cookie / workspace_id when ours are empty.

        Lets a desktop client that re-registers without a fresh browser
        cookie keep using the cookie a programmatic client already
        provided for the same opencode-go fingerprint.
        """
        inherited_session = getattr(other, "session_cookie", "")
        if not self.session_cookie and inherited_session:
            self.session_cookie = inherited_session
        inherited_cookie = getattr(other, "auth_cookie", "")
        if not self.auth_cookie and inherited_cookie:
            self.auth_cookie = inherited_cookie
        inherited_ws = getattr(other, "workspace_id", "")
        if not self.workspace_id and inherited_ws:
            self.workspace_id = inherited_ws

    def _fetch_status(self, timeout: int = 10) -> dict:
        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json",
            "Authorization": f"Bearer {self.session_cookie}",
            "x-org-id": self.workspace_id,
        }
        req = urllib.request.Request(CONSOLE_STATUS_URL, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    @staticmethod
    def _parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _windows_from_status(self, status: dict) -> dict[str, WindowUsage]:
        access = status.get("access") or {}
        meters = access.get("meters") or {}
        windows: dict[str, WindowUsage] = {}
        for meter_key, window_name in _METER_WINDOWS.items():
            meter = meters.get(meter_key)
            if not isinstance(meter, dict):
                continue
            try:
                limit = int(meter["limitMicroCents"])
                used = int(meter["usedMicroCents"])
            except (KeyError, TypeError, ValueError):
                continue
            utilization = max(0.0, min(100.0, used / limit * 100.0)) if limit > 0 else 0.0
            windows[window_name] = WindowUsage(
                utilization=utilization,
                resets_at=self._parse_iso(meter.get("resetsAt")) or self._parse_iso(access.get("endsAt")),
                metadata={
                    "used_micro_cents": used,
                    "limit_micro_cents": limit,
                    "source": "console_api",
                },
            )
        return windows

    def _fetch_html(self, timeout: int = 10) -> str:
        url = f"{DASHBOARD_URL_PREFIX}{urllib.parse.quote(self.workspace_id, safe='')}{DASHBOARD_URL_SUFFIX}"
        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cookie": f"auth={self.auth_cookie}",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def fetch(self) -> UsageResult:
        if not self.workspace_id:
            return UsageResult(provider=self.name, error="no workspace_id")

        if self.session_cookie:
            try:
                status = self._fetch_status()
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    return UsageResult(
                        provider=self.name,
                        error=f"HTTP {e.code} — console session expired",
                    )
                return UsageResult(provider=self.name, error=f"HTTP {e.code}")
            except urllib.error.URLError as e:
                return UsageResult(provider=self.name, error=f"network error: {e.reason}")
            except Exception as e:  # noqa: BLE001
                return UsageResult(provider=self.name, error=f"unexpected error: {e}")
            windows = self._windows_from_status(status)
            if windows:
                return UsageResult(provider=self.name, windows=windows)
            return UsageResult(
                provider=self.name,
                error="console status had no meters (access missing?)",
            )

        if not self.auth_cookie:
            return UsageResult(
                provider=self.name,
                error=(
                    "no session_cookie — set __Host-console_session from "
                    "opencode.ai DevTools (or an auth_cookie for legacy scrape)"
                ),
            )

        try:
            html = self._fetch_html()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return UsageResult(
                    provider=self.name,
                    error=f"HTTP {e.code} — auth cookie expired",
                )
            return UsageResult(provider=self.name, error=f"HTTP {e.code}")
        except urllib.error.URLError as e:
            return UsageResult(provider=self.name, error=f"network error: {e.reason}")
        except Exception as e:  # noqa: BLE001
            return UsageResult(provider=self.name, error=f"unexpected error: {e}")

        windows: dict[str, WindowUsage] = {}
        now = datetime.now(timezone.utc)
        for window_name, patterns in _WINDOW_KEYS.items():
            parsed = _parse_window(html, patterns)
            if parsed is None:
                continue
            usage_pct, reset_in_sec = parsed
            utilisation = max(0.0, min(100.0, usage_pct))
            resets_at = now + timedelta(seconds=max(0.0, reset_in_sec))
            windows[window_name] = WindowUsage(
                utilization=utilisation,
                resets_at=resets_at,
                metadata={
                    "usage_percent": round(usage_pct, 4),
                    "reset_in_sec": int(reset_in_sec),
                },
            )

        if not windows:
            return UsageResult(
                provider=self.name,
                error=(
                    "could not parse dashboard hydration "
                    "(rollingUsage/weeklyUsage/monthlyUsage) — "
                    "markup may have changed"
                ),
            )

        return UsageResult(provider=self.name, windows=windows)
