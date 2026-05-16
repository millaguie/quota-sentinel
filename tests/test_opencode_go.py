"""Tests for the OpenCode Go dashboard-scrape provider."""

from __future__ import annotations

import urllib.error
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from quota_sentinel.providers.opencode_go import (
    DASHBOARD_URL_PREFIX,
    DASHBOARD_URL_SUFFIX,
    OpencodeGoUsageProvider,
    _parse_window,
    _WINDOW_KEYS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


GOOD_HTML = (
    "<!doctype html><html><body><script>"
    "window._$HY={r:{},c:{}};"
    "rollingUsage:$R[12]={usagePercent:42.5,resetInSec:7200,limit:12}"
    "weeklyUsage:$R[13]={resetInSec:432000,usagePercent:18,limit:30}"
    "monthlyUsage:$R[14]={usagePercent:5.25,resetInSec:1900000,limit:60}"
    "</script></body></html>"
)

NO_HYDRATION_HTML = "<!doctype html><html><body><h1>Logged out</h1></body></html>"

PARTIAL_HTML = (
    "<!doctype html><html><body><script>"
    "rollingUsage:$R[1]={usagePercent:0,resetInSec:0}"
    "</script></body></html>"
)


# ── Regex / parser unit tests ────────────────────────────────────────────


def test_parse_window_pct_first():
    parsed = _parse_window(GOOD_HTML, _WINDOW_KEYS["rolling_5h"])
    assert parsed is not None
    pct, reset = parsed
    assert pct == 42.5
    assert reset == 7200.0


def test_parse_window_reset_first():
    parsed = _parse_window(GOOD_HTML, _WINDOW_KEYS["weekly"])
    assert parsed is not None
    pct, reset = parsed
    assert pct == 18.0
    assert reset == 432000.0


def test_parse_window_monthly_pct_first():
    parsed = _parse_window(GOOD_HTML, _WINDOW_KEYS["monthly"])
    assert parsed is not None
    pct, reset = parsed
    assert pct == 5.25
    assert reset == 1900000.0


def test_parse_window_missing_returns_none():
    assert _parse_window(NO_HYDRATION_HTML, _WINDOW_KEYS["rolling_5h"]) is None


# ── Provider behaviour ────────────────────────────────────────────────────


def test_fetch_requires_workspace_id():
    provider = OpencodeGoUsageProvider(workspace_id="", auth_cookie="abc")
    result = provider.fetch()
    assert result.error == "no workspace_id"
    assert result.windows == {}


def test_fetch_requires_auth_cookie():
    provider = OpencodeGoUsageProvider(workspace_id="ws-uuid", auth_cookie="")
    result = provider.fetch()
    assert result.error is not None
    assert "auth_cookie" in result.error
    assert result.windows == {}


def test_fetch_parses_all_three_windows():
    provider = OpencodeGoUsageProvider(workspace_id="ws-uuid", auth_cookie="cookieval")
    with patch.object(provider, "_fetch_html", return_value=GOOD_HTML):
        before = datetime.now(timezone.utc)
        result = provider.fetch()
        after = datetime.now(timezone.utc)

    assert result.error is None
    assert set(result.windows) == {"rolling_5h", "weekly", "monthly"}

    rolling = result.windows["rolling_5h"]
    assert rolling.utilization == pytest.approx(42.5)
    assert rolling.metadata is not None
    assert rolling.metadata["reset_in_sec"] == 7200
    assert rolling.resets_at is not None
    # resets_at = now + reset_in_sec  → must land in the [before+7200s, after+7200s] window
    delta = (rolling.resets_at - before).total_seconds()
    assert 7200 <= delta <= 7200 + (after - before).total_seconds() + 1

    weekly = result.windows["weekly"]
    assert weekly.utilization == pytest.approx(18.0)
    assert weekly.metadata is not None
    assert weekly.metadata["reset_in_sec"] == 432000

    monthly = result.windows["monthly"]
    assert monthly.utilization == pytest.approx(5.25)


def test_fetch_clamps_utilisation():
    """If the dashboard ever reports a value <0 or >100, clamp to [0, 100]."""
    weird_html = (
        "rollingUsage:$R[1]={usagePercent:-5,resetInSec:60}"
        "weeklyUsage:$R[2]={usagePercent:150,resetInSec:60}"
        "monthlyUsage:$R[3]={usagePercent:50,resetInSec:60}"
    )
    provider = OpencodeGoUsageProvider(workspace_id="ws", auth_cookie="c")
    with patch.object(provider, "_fetch_html", return_value=weird_html):
        result = provider.fetch()
    assert result.windows["rolling_5h"].utilization == 0.0
    assert result.windows["weekly"].utilization == 100.0
    assert result.windows["monthly"].utilization == 50.0


def test_fetch_handles_partial_dashboard():
    provider = OpencodeGoUsageProvider(workspace_id="ws", auth_cookie="c")
    with patch.object(provider, "_fetch_html", return_value=PARTIAL_HTML):
        result = provider.fetch()
    assert result.error is None
    assert set(result.windows) == {"rolling_5h"}


def test_fetch_returns_error_when_dashboard_markup_unknown():
    provider = OpencodeGoUsageProvider(workspace_id="ws", auth_cookie="c")
    with patch.object(provider, "_fetch_html", return_value=NO_HYDRATION_HTML):
        result = provider.fetch()
    assert result.windows == {}
    assert result.error is not None
    assert "markup" in result.error


def test_fetch_handles_http_401_as_expired_cookie():
    provider = OpencodeGoUsageProvider(workspace_id="ws", auth_cookie="c")
    err = urllib.error.HTTPError(
        url="x",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    with patch.object(provider, "_fetch_html", side_effect=err):
        result = provider.fetch()
    assert result.windows == {}
    assert result.error is not None
    assert "401" in result.error
    assert "cookie" in result.error.lower()


def test_fetch_handles_network_error():
    provider = OpencodeGoUsageProvider(workspace_id="ws", auth_cookie="c")
    err = urllib.error.URLError("connection refused")
    with patch.object(provider, "_fetch_html", side_effect=err):
        result = provider.fetch()
    assert result.windows == {}
    assert result.error is not None
    assert "network error" in result.error


def test_dashboard_url_construction():
    """Workspace ID with special chars must be URL-encoded."""
    provider = OpencodeGoUsageProvider(
        workspace_id="ws id with spaces", auth_cookie="c"
    )
    captured = {}

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        _ = timeout  # required-by-signature, unused in this stub
        captured["url"] = req.full_url
        captured["cookie"] = req.get_header("Cookie")

        class _R:
            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                _ = exc_info
                return False

        return _R()

    with patch("urllib.request.urlopen", fake_urlopen):
        provider._fetch_html()  # noqa: SLF001 — internal API under test

    expected_url = (
        f"{DASHBOARD_URL_PREFIX}ws%20id%20with%20spaces{DASHBOARD_URL_SUFFIX}"
    )
    assert captured["url"] == expected_url
    assert captured["cookie"] == "auth=c"


# ── Factory wiring ────────────────────────────────────────────────────────


def test_create_provider_returns_opencode_go():
    from quota_sentinel.providers import AUTH_KEY_TO_PROVIDER, create_provider

    assert AUTH_KEY_TO_PROVIDER["opencode-go"] == "opencode_go"
    provider = create_provider(
        "opencode_go",
        {"key": "sk-xxx", "workspace_id": "ws", "auth_cookie": "c"},
    )
    assert isinstance(provider, OpencodeGoUsageProvider)
    assert provider.workspace_id == "ws"
    assert provider.auth_cookie == "c"
    assert provider.api_token == "sk-xxx"
