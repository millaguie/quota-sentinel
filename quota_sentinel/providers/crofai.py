"""CrofAI usage provider — session-cookie based (no public quota API)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage

USABLE_REQUESTS_URL = "https://crof.ai/u_v2/get_usable_requests"
CREDITS_URL = "https://crof.ai/user-api/credits"
DASHBOARD_URL = "https://crof.ai/dashboard"

# Pattern matching the dashboard's server-rendered ``usable / plan`` display:
#
#     <pretty id="usable_requests">2872.5/6250</pretty>
#
# crof.ai computes the plan ceiling server-side based on the user's plan name
# (encoded in the session cookie — e.g. ``plan: "ent1"`` → 6250/day) and only
# exposes the ceiling through this rendered string.  There's no JSON endpoint
# that returns the plan size, so we scrape it once and cache the value on the
# provider instance.
#
# The ``usable`` numerator is fractional now (e.g. ``2872.5``), so the
# numerator pattern must allow a decimal — an integer-only ``\d+`` stopped
# matching and silently dropped the plan ceiling.
_PLAN_RE = re.compile(
    r'<pretty[^>]*id="usable_requests"[^>]*>\s*\d+(?:\.\d+)?\s*/\s*(\d+)\s*</pretty>',
    re.IGNORECASE,
)

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _get_with_cookie(url: str, session_cookie: str, timeout: int = 10) -> Any:
    """GET request with a session cookie, returning parsed JSON or raw text."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Cookie": f"session={session_cookie}",
        "Referer": "https://crof.ai/dashboard",
        "User-Agent": _BROWSER_UA,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
    try:
        return json.loads(body)
    except ValueError:
        return body.strip()


def _fetch_plan_from_dashboard(session_cookie: str, timeout: int = 10) -> int | None:
    """Scrape the daily request plan size from the dashboard HTML.

    Returns the integer ceiling (e.g. ``7500``) or ``None`` if the page
    couldn't be fetched / parsed.  Callers should cache the result —
    the ceiling is static per plan, so one scrape per process is enough.
    """
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cookie": f"session={session_cookie}",
        "User-Agent": _BROWSER_UA,
    }
    try:
        req = urllib.request.Request(DASHBOARD_URL, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
    except Exception:
        return None
    m = _PLAN_RE.search(body)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


class CrofAIUsageProvider(UsageProvider):
    """CrofAI — subscription request quota via authenticated dashboard endpoint.

    CrofAI has no public quota API. The dashboard exposes a ``usable_requests``
    endpoint that requires a Flask ``session`` cookie obtained from the user's
    browser after logging into https://crof.ai.
    """

    name = "crofai"

    def __init__(self, session_cookie: str = "", api_token: str = ""):
        self.session_cookie = session_cookie
        self.api_token = api_token  # unused for quota, kept for fingerprinting

    def merge_credentials_from(self, other):
        """Adopt ``other``'s session_cookie when our own is empty.

        Lets a desktop client that re-registers without a fresh browser
        cookie keep using the cookie a programmatic client already
        provided for the same nahcrof_* fingerprint.
        """
        inherited = getattr(other, "session_cookie", "")
        if not self.session_cookie and inherited:
            self.session_cookie = inherited
        # The /u_v2/get_usable_requests endpoint returns ONLY the remaining
        # count as a bare JSON number — fractional now, e.g. ``2872.5``.
        # crof.ai's API doesn't
        # expose the plan ceiling anywhere — only the dashboard HTML
        # renders it (e.g. ``248/7500``).  We scrape it once via
        # ``_fetch_plan_from_dashboard`` and cache it on the instance.
        # If the scrape fails (network blip, plan element renamed), fall
        # back to ``_reference_plan`` — the max-ever-seen heuristic —
        # which at least self-corrects after a daily reset bumps the
        # ``usable`` count back to the real ceiling.
        self._reference_plan: int | None = None
        self._scraped_plan: int | None = None

    def fetch(self) -> UsageResult:
        if not self.session_cookie:
            return UsageResult(provider=self.name, error="no session_cookie")

        try:
            data = _get_with_cookie(USABLE_REQUESTS_URL, self.session_cookie)
        except urllib.error.HTTPError as e:
            return UsageResult(provider=self.name, error=f"HTTP {e.code}")
        except urllib.error.URLError as e:
            return UsageResult(provider=self.name, error=f"network error: {e.reason}")
        except Exception as e:
            return UsageResult(provider=self.name, error=f"unexpected error: {e}")

        usable: float | None = None
        plan: int | None = None
        if isinstance(data, dict):
            try:
                usable = float(data.get("usable_requests") or 0)
            except (TypeError, ValueError):
                usable = None
            try:
                plan = int(data.get("requests_plan") or 0)
            except (TypeError, ValueError):
                plan = None
        elif isinstance(data, (int, float)):
            usable = float(data)

        if usable is None:
            return UsageResult(
                provider=self.name, error="malformed usable_requests response"
            )

        # Plan ceiling resolution order:
        # 1. Field in the JSON response (in case crof.ai ever ships one).
        # 2. Cached scrape of the dashboard HTML (the real source of truth —
        #    rendered as ``<pretty id="usable_requests">248/7500</pretty>``).
        # 3. Reference-plan heuristic (max value ever seen on this provider).
        #
        # Only attempt the scrape when we don't have a JSON plan and the
        # cached scrape value is still missing — once we know the ceiling
        # it doesn't change for the life of the plan.
        if plan is None or plan <= 0:
            if self._scraped_plan is None:
                self._scraped_plan = _fetch_plan_from_dashboard(self.session_cookie)
            if self._scraped_plan and self._scraped_plan > 0:
                plan = self._scraped_plan
            else:
                if self._reference_plan is None or usable > self._reference_plan:
                    self._reference_plan = max(int(usable), 1)
                plan = self._reference_plan

        used = max(plan - usable, 0)
        utilization = min(used / plan * 100, 100.0) if plan > 0 else 0.0

        metadata: dict[str, Any] = {
            "usable_requests": usable,
            "requests_plan": plan,
        }

        # Optional: credits balance (best-effort, non-fatal)
        try:
            credits_body = _get_with_cookie(CREDITS_URL, self.session_cookie)
            if isinstance(credits_body, str) and credits_body.lower() != "no":
                metadata["credits"] = float(credits_body.strip().strip('"').lstrip("$"))
            elif isinstance(credits_body, (int, float)):
                metadata["credits"] = float(credits_body)
        except Exception:
            pass

        return UsageResult(
            provider=self.name,
            windows={
                "requests": WindowUsage(
                    utilization=utilization,
                    resets_at=None,
                    metadata=metadata,
                )
            },
        )
