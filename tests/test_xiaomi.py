"""Tests for the Xiaomi MiMo Token Plan provider."""

from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from quota_sentinel.providers.xiaomi import (
    USAGE_URL,
    XiaomiTokenPlanUsageProvider,
    _clamp_pct,
    _coerce_int,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


GOOD_RESPONSE = {
    "code": 0,
    "data": {
        "usage": {
            "items": [
                {
                    "name": "plan_total_token",
                    "used": 12_000_000,
                    "limit": 60_000_000,
                    "percent": 20,
                },
                {
                    "name": "compensation_total_token",
                    "used": 500_000,
                    "limit": 1_000_000,
                    "percent": 50,
                },
            ]
        },
        "monthUsage": {
            "items": [
                {
                    "name": "month_total_token",
                    "used": 12_500_000,
                    "limit": 61_000_000,
                    "percent": 20.49,
                }
            ]
        },
    },
}


# ── Helper unit tests ─────────────────────────────────────────────────────


def test_clamp_pct_normal():
    assert _clamp_pct(42.5) == 42.5


def test_clamp_pct_low_clipped_to_zero():
    assert _clamp_pct(-5) == 0.0


def test_clamp_pct_high_clipped_to_hundred():
    assert _clamp_pct(150) == 100.0


def test_clamp_pct_none_is_zero():
    assert _clamp_pct(None) == 0.0


def test_clamp_pct_invalid_string_is_zero():
    assert _clamp_pct("not a number") == 0.0


def test_coerce_int_from_int():
    assert _coerce_int(7) == 7


def test_coerce_int_from_float_string():
    assert _coerce_int("12.7") == 12


def test_coerce_int_none_passthrough():
    assert _coerce_int(None) is None


# ── Provider behaviour ────────────────────────────────────────────────────


def test_fetch_requires_session_cookie():
    provider = XiaomiTokenPlanUsageProvider(session_cookie="")
    result = provider.fetch()
    assert result.error == "no session_cookie"
    assert result.windows == {}


def test_fetch_parses_all_three_windows():
    provider = XiaomiTokenPlanUsageProvider(session_cookie="abc")
    with patch("quota_sentinel.providers.xiaomi.http_get", return_value=GOOD_RESPONSE):
        result = provider.fetch()

    assert result.error is None
    assert set(result.windows) == {"plan", "compensation", "monthly"}

    plan = result.windows["plan"]
    assert plan.utilization == pytest.approx(20.0)
    assert plan.metadata is not None
    assert plan.metadata["used_tokens"] == 12_000_000
    assert plan.metadata["limit_tokens"] == 60_000_000
    assert plan.metadata["item_name"] == "plan_total_token"
    assert plan.resets_at is None

    comp = result.windows["compensation"]
    assert comp.utilization == pytest.approx(50.0)

    monthly = result.windows["monthly"]
    assert monthly.utilization == pytest.approx(20.49)


def test_fetch_clamps_utilisation():
    """Out-of-range percents from the console must be clamped to [0, 100]."""
    weird = {
        "code": 0,
        "data": {
            "usage": {
                "items": [
                    {
                        "name": "plan_total_token",
                        "used": -1,
                        "limit": 10,
                        "percent": -10,
                    },
                    {
                        "name": "compensation_total_token",
                        "used": 999,
                        "limit": 10,
                        "percent": 999,
                    },
                ]
            }
        },
    }
    provider = XiaomiTokenPlanUsageProvider(session_cookie="c")
    with patch("quota_sentinel.providers.xiaomi.http_get", return_value=weird):
        result = provider.fetch()
    assert result.windows["plan"].utilization == 0.0
    assert result.windows["compensation"].utilization == 100.0


def test_fetch_derives_percent_when_missing():
    """Fall back to used/limit when the console omits the convenience percent."""
    no_pct = {
        "code": 0,
        "data": {
            "usage": {
                "items": [
                    {"name": "plan_total_token", "used": 25, "limit": 100},
                ]
            }
        },
    }
    provider = XiaomiTokenPlanUsageProvider(session_cookie="c")
    with patch("quota_sentinel.providers.xiaomi.http_get", return_value=no_pct):
        result = provider.fetch()
    assert result.windows["plan"].utilization == pytest.approx(25.0)


def test_fetch_skips_unknown_item_names():
    """Unknown ``items[].name`` rows must be ignored rather than crashing."""
    mixed = {
        "code": 0,
        "data": {
            "usage": {
                "items": [
                    {"name": "plan_total_token", "percent": 10},
                    {"name": "something_new", "percent": 99},
                ]
            }
        },
    }
    provider = XiaomiTokenPlanUsageProvider(session_cookie="c")
    with patch("quota_sentinel.providers.xiaomi.http_get", return_value=mixed):
        result = provider.fetch()
    assert set(result.windows) == {"plan"}


def test_fetch_handles_empty_payload():
    empty = {"code": 0, "data": {"usage": {"items": []}}}
    provider = XiaomiTokenPlanUsageProvider(session_cookie="c")
    with patch("quota_sentinel.providers.xiaomi.http_get", return_value=empty):
        result = provider.fetch()
    assert result.windows == {}
    assert result.error is not None
    assert "no usage windows" in result.error


def test_fetch_handles_api_error_code():
    err = {"code": 401, "message": "session expired"}
    provider = XiaomiTokenPlanUsageProvider(session_cookie="c")
    with patch("quota_sentinel.providers.xiaomi.http_get", return_value=err):
        result = provider.fetch()
    assert result.windows == {}
    assert result.error is not None
    assert "session expired" in result.error


def test_fetch_handles_http_401_as_expired_cookie():
    provider = XiaomiTokenPlanUsageProvider(session_cookie="c")
    err = urllib.error.HTTPError(
        url="x",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,  # type: ignore[arg-type]
    )
    with patch("quota_sentinel.providers.xiaomi.http_get", side_effect=err):
        result = provider.fetch()
    assert result.windows == {}
    assert result.error is not None
    assert "401" in result.error
    assert "cookie" in result.error.lower()


def test_fetch_handles_rate_limited():
    provider = XiaomiTokenPlanUsageProvider(session_cookie="c")
    err = urllib.error.HTTPError(
        url="x",
        code=429,
        msg="Too Many Requests",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,  # type: ignore[arg-type]
    )
    with patch("quota_sentinel.providers.xiaomi.http_get", side_effect=err):
        result = provider.fetch()
    assert result.error == "rate limited"


def test_fetch_handles_network_error():
    provider = XiaomiTokenPlanUsageProvider(session_cookie="c")
    err = urllib.error.URLError("connection refused")
    with patch("quota_sentinel.providers.xiaomi.http_get", side_effect=err):
        result = provider.fetch()
    assert result.windows == {}
    assert result.error is not None
    assert "network error" in result.error


def test_cookie_header_passes_through_when_already_named():
    """If the operator pasted ``name=value`` pairs, send them verbatim."""
    provider = XiaomiTokenPlanUsageProvider(session_cookie="foo=bar; baz=qux")
    captured: dict[str, str] = {}

    def fake_http_get(url: str, headers: dict[str, str]):  # type: ignore[no-untyped-def]
        _ = url  # required-by-signature, unused in this stub
        captured.update(headers)
        return GOOD_RESPONSE

    with patch("quota_sentinel.providers.xiaomi.http_get", side_effect=fake_http_get):
        provider.fetch()

    assert captured["Cookie"] == "foo=bar; baz=qux"


def test_cookie_header_wraps_bare_value():
    """A bare cookie value gets wrapped in ``session=<value>``."""
    provider = XiaomiTokenPlanUsageProvider(session_cookie="abc123")
    captured: dict[str, str] = {}

    def fake_http_get(url: str, headers: dict[str, str]):  # type: ignore[no-untyped-def]
        _ = url  # required-by-signature, unused in this stub
        captured.update(headers)
        return GOOD_RESPONSE

    with patch("quota_sentinel.providers.xiaomi.http_get", side_effect=fake_http_get):
        provider.fetch()

    assert captured["Cookie"] == "session=abc123"


def test_usage_url_targets_platform_console():
    """The provider must hit the platform console, NOT the regional model host."""
    assert USAGE_URL.startswith("https://platform.xiaomimimo.com/")
    assert "tokenPlan/usage" in USAGE_URL


# ── Factory wiring ────────────────────────────────────────────────────────


def test_create_provider_returns_xiaomi():
    from quota_sentinel.providers import AUTH_KEY_TO_PROVIDER, create_provider

    assert AUTH_KEY_TO_PROVIDER["xiaomi-token-plan-ams"] == "xiaomi"
    assert AUTH_KEY_TO_PROVIDER["xiaomi-token-plan-cn"] == "xiaomi"
    assert AUTH_KEY_TO_PROVIDER["xiaomi-token-plan-sgp"] == "xiaomi"
    provider = create_provider(
        "xiaomi",
        {"key": "tp-xxx", "session_cookie": "abc"},
    )
    assert isinstance(provider, XiaomiTokenPlanUsageProvider)
    assert provider.session_cookie == "abc"
    assert provider.api_token == "tp-xxx"


# ── Credential merging (cookie sharing across clients) ────────────────────


def test_merge_credentials_adopts_cookie_when_empty():
    """An empty-cookie client inherits the cookie from a peer sharing
    the same ``tp-*`` fingerprint."""
    empty = XiaomiTokenPlanUsageProvider(session_cookie="", api_token="tp-x")
    holder = XiaomiTokenPlanUsageProvider(
        session_cookie="from-browser", api_token="tp-x"
    )

    empty.merge_credentials_from(holder)

    assert empty.session_cookie == "from-browser"


def test_merge_credentials_keeps_own_cookie_when_present():
    """A client with its own fresh cookie wins — no overwrite."""
    fresh = XiaomiTokenPlanUsageProvider(session_cookie="mine", api_token="tp-x")
    stale = XiaomiTokenPlanUsageProvider(session_cookie="theirs", api_token="tp-x")

    fresh.merge_credentials_from(stale)

    assert fresh.session_cookie == "mine"


def test_merge_credentials_no_op_when_other_is_empty():
    """Nothing to inherit from an empty-cookie peer."""
    self_ = XiaomiTokenPlanUsageProvider(session_cookie="", api_token="tp-x")
    peer = XiaomiTokenPlanUsageProvider(session_cookie="", api_token="tp-x")

    self_.merge_credentials_from(peer)

    assert self_.session_cookie == ""
