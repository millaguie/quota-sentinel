"""Alibaba Cloud Model Studio **Token Plan (Team Edition)** usage provider.

Distinct from :mod:`quota_sentinel.providers.alibaba` (the *Coding Plan*).
The Token Plan (Team Edition) is a seat-based subscription billed in
**Credits**; there is **no public/API-key usage endpoint** for it — the only
way to read remaining Credits is the same undocumented console RPC the
"My Subscriptions" page uses, behind the operator's logged-in browser
session.

Reverse-engineering source: ``steipete/CodexBar`` (``docs/alibaba-token-plan.md``)::

    POST https://bailian.console.aliyun.com/data/api.json
         ?action=GetSubscriptionSummary&product=BssOpenAPI-V3&_tag=
    (form-encoded)
      product=BssOpenAPI-V3
      action=GetSubscriptionSummary
      region=cn-beijing
      params={"ProductCode":"sfm_tokenplanteams_dp_cn"}
    Cookie: <aliyun console session>   (+ sec_token when resolvable)

Response carries ``TotalValue`` (total Credits granted), ``TotalSurplusValue``
(Credits remaining), ``TotalCount`` (active subscriptions) and
``NearestExpireDate``.  Utilisation = (Total - Surplus) / Total * 100.

The intl seat ProductCode is ``sfm_tokenplanteams_dp_intl`` (the
``…teamsaddon…`` variant is the shared-pack add-on and reads 0 unless
purchased). ``sec_token`` is mandatory and goes in the form body together
with ``region=cn-hangzhou`` (the BSS service region, not the model region).
The token is session-scoped and rotates, so the provider re-scrapes it from
the dashboard HTML each poll (see ``_scrape_sec_token``). The response parser
searches recursively for ``TotalSurplusValue`` so minor nesting changes are
tolerated.

Required ``provider_config``:
  - ``session_cookie`` — value of the aliyun console session cookie (login
    cookie for ``*.console.aliyun.com`` / ``account.alibabacloud.com``).
    Refresh from DevTools when the meter reports ``HTTP 401`` /
    ``ConsoleNeedLogin``.
Optional:
  - ``sec_token`` — anti-CSRF token scraped from the dashboard page.
  - ``api_token`` — the ``sk-ws-*`` workspace key (fingerprinting only;
    NOT usable for this endpoint).
  - ``region`` — ``"intl"`` (default) or ``"cn"``.
"""

from __future__ import annotations

import json
import re
import urllib.error
from datetime import UTC, datetime
from typing import Any

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_get_text, http_post_form

# Verified 2026-07-01 against a real intl console capture: the ``region`` in
# the request *body* is the BSS service region (``cn-hangzhou``), NOT the model
# region; ``sec_token`` is mandatory and goes in the body; the seat plan's
# ProductCode is ``sfm_tokenplanteams_dp_intl`` (the ``…teamsaddon…`` variant is
# the shared-pack add-on and reads 0 unless purchased).  The ``sec_token`` is
# session-scoped and rotates; it is embedded verbatim in the dashboard HTML
# (``SEC_TOKEN: "<value>"``), so the provider re-scrapes it from ``dash_url``
# with the cookie on every poll rather than relying on a stale pasted value.
_TOKEN_PLAN_REGIONS = {
    "intl": {
        "host": "https://modelstudio.console.alibabacloud.com",
        "dash_url": "https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=plan",
        "body_region": "cn-hangzhou",
        "product_code": "sfm_tokenplanteams_dp_intl",
    },
    "cn": {
        "host": "https://bailian.console.aliyun.com",
        "dash_url": "https://bailian.console.aliyun.com/?tab=plan",  # not verified
        "body_region": "cn-beijing",  # CodexBar; not independently verified
        "product_code": "sfm_tokenplanteams_dp_cn",
    },
}

# ``SEC_TOKEN: "abc123"`` in the dashboard page source (quotes/space optional).
_SEC_TOKEN_RE = re.compile(r"""SEC_TOKEN["'\s:=]+([A-Za-z0-9_-]{8,})""")


class AlibabaTokenPlanUsageProvider(UsageProvider):
    """Alibaba Model Studio Token Plan (Team Edition) — Credits balance.

    Cookie-gated console RPC (``GetSubscriptionSummary``); no API-key path.
    """

    name = "alibaba_token_plan"

    def __init__(
        self,
        session_cookie: str = "",
        sec_token: str = "",
        api_token: str = "",
        region: str = "intl",
    ):
        self.session_cookie = session_cookie.strip()
        self.sec_token = sec_token.strip()
        self.api_token = api_token
        self.region = region

    def merge_credentials_from(self, other: UsageProvider) -> None:
        """Keep a working cookie/sec_token when a re-registration lacks one."""
        if not self.session_cookie:
            self.session_cookie = getattr(other, "session_cookie", "")
        if not self.sec_token:
            self.sec_token = getattr(other, "sec_token", "")

    def _scrape_sec_token(self, dash_url: str) -> str:
        """Pull the session ``sec_token`` out of the dashboard page HTML.

        The token is embedded verbatim (``SEC_TOKEN: "<value>"``) and is the
        same value the browser submits, so a plain cookie-authenticated GET +
        regex is enough — no JS execution required.
        """
        try:
            html = http_get_text(dash_url, headers={"Cookie": self.session_cookie})
        except Exception:  # noqa: BLE001 - scraping is best-effort
            return ""
        m = _SEC_TOKEN_RE.search(html)
        return m.group(1) if m else ""

    def fetch(self) -> UsageResult:
        if not self.session_cookie:
            return UsageResult(provider=self.name, error="no session_cookie")

        rcfg = _TOKEN_PLAN_REGIONS.get(self.region, _TOKEN_PLAN_REGIONS["intl"])
        # A manually-pinned sec_token wins; otherwise scrape a fresh one from
        # the dashboard (it rotates per session).
        sec_token = self.sec_token or self._scrape_sec_token(rcfg["dash_url"])
        if not sec_token:
            return UsageResult(provider=self.name, error="no sec_token")

        url = (
            f"{rcfg['host']}/data/api.json"
            f"?action=GetSubscriptionSummary&product=BssOpenAPI-V3&_tag="
        )
        # ``sec_token`` and ``region`` (BSS service region) go in the form body;
        # the optional ``collina``/``umid`` risk-control fingerprints are NOT
        # required (verified: the request succeeds without them).
        fields = {
            "product": "BssOpenAPI-V3",
            "action": "GetSubscriptionSummary",
            "params": json.dumps({"ProductCode": rcfg["product_code"]}),
            "sec_token": sec_token,
            "region": rcfg["body_region"],
        }
        headers = {"Cookie": self.session_cookie, "bx-v": "2.5.36"}

        try:
            data = http_post_form(url, fields, headers=headers)
        except urllib.error.HTTPError as e:
            error_map = {401: "auth failed", 403: "forbidden", 429: "rate limited"}
            return UsageResult(
                provider=self.name, error=error_map.get(e.code, f"HTTP {e.code}")
            )
        except Exception as e:  # noqa: BLE001 - surface any transport error
            return UsageResult(provider=self.name, error=str(e))

        code = data.get("code") if isinstance(data, dict) else None
        if code in {"ConsoleNeedLogin", "NeedLogin"}:
            return UsageResult(provider=self.name, error="ConsoleNeedLogin")
        # Stale/missing sec_token → console returns a *200 envelope* with a
        # token error code rather than an HTTP 4xx.
        if isinstance(code, str) and "Token" in code:
            return UsageResult(provider=self.name, error="sec_token expired")

        summary = self._find_summary(data)
        if not summary:
            return UsageResult(provider=self.name, error="no subscription data")

        total = _to_float(summary.get("TotalValue"))
        surplus = _to_float(summary.get("TotalSurplusValue"))
        if total is None or surplus is None or total <= 0:
            return UsageResult(provider=self.name, error="no credit totals")

        used = max(total - surplus, 0.0)
        pct = min(used / total * 100, 100.0)
        resets_at = self._parse_reset(summary.get("NearestExpireDate"))
        windows = {
            "credits": WindowUsage(
                pct,
                resets_at,
                metadata={
                    "total_credits": total,
                    "remaining_credits": surplus,
                    "used_credits": used,
                    "active_subscriptions": summary.get("TotalCount"),
                },
            )
        }
        return UsageResult(provider=self.name, windows=windows)

    @staticmethod
    def _find_summary(data: Any) -> dict | None:
        """Recursively locate the dict carrying ``TotalSurplusValue``."""
        return AlibabaTokenPlanUsageProvider._search(data, depth=0)

    @staticmethod
    def _search(obj: Any, depth: int) -> dict | None:
        if depth > 6:
            return None
        if isinstance(obj, dict):
            if "TotalSurplusValue" in obj or "TotalValue" in obj:
                return obj
            for v in obj.values():
                found = AlibabaTokenPlanUsageProvider._search(v, depth + 1)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = AlibabaTokenPlanUsageProvider._search(item, depth + 1)
                if found:
                    return found
        return None

    @staticmethod
    def _parse_reset(value: Any) -> datetime | None:
        if value in (None, "", 0):
            return None
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value / 1000, tz=UTC)
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (ValueError, TypeError, OSError):
            return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
