"""CrofAI usage provider — session-cookie based (no public quota API)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage

USABLE_REQUESTS_URL = "https://crof.ai/u_v2/get_usable_requests"
CREDITS_URL = "https://crof.ai/user-api/credits"

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
        # The /u_v2/get_usable_requests endpoint often returns just the number
        # of remaining requests (plain JSON number). Without a plan ceiling in
        # the response, we treat the first observed value as the reference
        # "full quota" and compute utilization from there (like deepseek/chutes
        # balance tracking).
        self._reference_plan: int | None = None

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

        usable: int | None = None
        plan: int | None = None
        if isinstance(data, dict):
            try:
                usable = int(data.get("usable_requests") or 0)
            except (TypeError, ValueError):
                usable = None
            try:
                plan = int(data.get("requests_plan") or 0)
            except (TypeError, ValueError):
                plan = None
        elif isinstance(data, (int, float)):
            usable = int(data)

        if usable is None:
            return UsageResult(
                provider=self.name, error="malformed usable_requests response"
            )

        # If plan wasn't provided, use reference tracking: first-seen value is
        # our best guess at "full plan capacity".
        if plan is None or plan <= 0:
            if self._reference_plan is None or usable > self._reference_plan:
                self._reference_plan = max(usable, 1)
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
