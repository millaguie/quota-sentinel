"""OpenCode Go usage provider — session-cookie based (no public quota API).

OpenCode's `Go` subscription plan (https://opencode.ai/docs/go/) does NOT
expose a programmatic usage endpoint — the open feature request
(https://github.com/anomalyco/opencode/issues/10448 for Zen balance,
https://github.com/anomalyco/opencode/issues/18648 for Go/Zen usage) is
still open.

Until that lands, the only way to read the user's $/5h, weekly, and
monthly utilisation is to scrape the workspace dashboard
(``https://opencode.ai/workspace/<workspace_id>/go``).  The page is
server-rendered with SolidJS; the hydration payload embedded in the HTML
contains ``rollingUsage``, ``weeklyUsage`` and ``monthlyUsage`` objects,
each with ``usagePercent`` and ``resetInSec`` fields.

Approach copied (with credit) from the open-source ``slkiser/opencode-quota``
StreamDeck plugin: https://github.com/slkiser/opencode-quota — which is the
only third-party tracker that has the regex right today.  The dashboard
markup can change at any time, so the scrape is best-effort.

Required ``provider_config`` (passed via the sentinel registration
payload, merged on top of the bare API key):

- ``workspace_id`` — UUID of the user's OpenCode workspace (from the URL
  bar after logging in at ``opencode.ai``)
- ``auth_cookie`` — value of the ``auth`` cookie issued by ``opencode.ai``
  after login.  Refresh from DevTools when the scrape starts returning
  HTTP 401/302.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage

DASHBOARD_URL_PREFIX = "https://opencode.ai/workspace/"
DASHBOARD_URL_SUFFIX = "/go"

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
    ):
        self.workspace_id = workspace_id.strip()
        self.auth_cookie = auth_cookie.strip()
        # Bearer key is kept for fingerprinting/registration only; the
        # ``/zen/go/v1`` API has no usage endpoint, so we never use it.
        self.api_token = api_token

    def merge_credentials_from(self, other):
        """Adopt ``other``'s auth_cookie / workspace_id when ours are empty.

        Lets a desktop client that re-registers without a fresh browser
        cookie keep using the cookie a programmatic client already
        provided for the same opencode-go fingerprint.
        """
        inherited_cookie = getattr(other, "auth_cookie", "")
        if not self.auth_cookie and inherited_cookie:
            self.auth_cookie = inherited_cookie
        inherited_ws = getattr(other, "workspace_id", "")
        if not self.workspace_id and inherited_ws:
            self.workspace_id = inherited_ws

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
        if not self.auth_cookie:
            return UsageResult(
                provider=self.name,
                error="no auth_cookie (refresh from opencode.ai DevTools)",
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
