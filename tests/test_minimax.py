"""Tests for the MiniMax coding-plan usage provider."""

from __future__ import annotations

import urllib.error
from unittest.mock import patch

from quota_sentinel.providers import create_provider
from quota_sentinel.providers.minimax import MiniMaxUsageProvider

# A representative ``/coding_plan/remains`` payload: one coding model with
# both an interval and a weekly window, plus a non-coding model (hailuo)
# that must be filtered out.
GOOD_RESPONSE = {
    "base_resp": {"status_code": 0, "status_msg": "success"},
    "model_remains": [
        {
            "model_name": "MiniMax-M2.5",
            "current_interval_total_count": 100,
            "current_interval_usage_count": 40,  # remaining, not used
            "remains_time": 3_600_000,
            "current_weekly_total_count": 1000,
            "current_weekly_usage_count": 250,
            "weekly_remains_time": 86_400_000,
        },
        {
            "model_name": "hailuo-video-01",
            "current_interval_total_count": 50,
            "current_interval_usage_count": 50,
            "remains_time": 0,
        },
    ],
}

COOKIE_MISSING_RESPONSE = {
    "base_resp": {"status_code": 1004, "status_msg": "cookie is missing, log in again"}
}


def _provider(**kwargs) -> MiniMaxUsageProvider:
    base = {"api_token": "sk-cp-x", "group_id": "grp-1", "session_cookie": "abc"}
    base.update(kwargs)
    return MiniMaxUsageProvider(**base)


# ── Required credentials ──────────────────────────────────────────────────


def test_fetch_requires_token():
    result = _provider(api_token="").fetch()
    assert result.error == "no token"


def test_fetch_requires_group_id():
    result = _provider(group_id="").fetch()
    assert result.error == "no group_id"


def test_fetch_requires_session_cookie():
    result = _provider(session_cookie="").fetch()
    assert result.error == "no session_cookie"


# ── Parsing ───────────────────────────────────────────────────────────────


def test_fetch_parses_interval_and_weekly_windows():
    provider = _provider()
    with patch("quota_sentinel.providers.minimax.http_get", return_value=GOOD_RESPONSE):
        result = provider.fetch()

    assert result.error is None
    # hailuo is filtered out; only the coding model survives.
    assert set(result.windows) == {"MM-M2.5_interval", "MM-M2.5_weekly"}
    # interval: total 100, remaining 40 → used 60 → 60%
    assert result.windows["MM-M2.5_interval"].utilization == 60.0
    # weekly: total 1000, remaining 250 → used 750 → 75%
    assert result.windows["MM-M2.5_weekly"].utilization == 75.0
    assert result.windows["MM-M2.5_interval"].resets_at is not None


def test_fetch_sends_cookie_header():
    provider = _provider(session_cookie="sessionid=xyz")
    with patch(
        "quota_sentinel.providers.minimax.http_get", return_value=GOOD_RESPONSE
    ) as mock_get:
        provider.fetch()

    headers = mock_get.call_args.kwargs["headers"]
    assert headers["cookie"] == "sessionid=xyz"
    assert headers["authorization"] == "Bearer sk-cp-x"


def test_bare_cookie_value_is_wrapped():
    provider = _provider(session_cookie="rawvalue")
    assert provider._build_cookie_header() == "session=rawvalue"


# ── Error handling ────────────────────────────────────────────────────────


def test_cookie_missing_status_code_maps_to_expired():
    provider = _provider()
    with patch(
        "quota_sentinel.providers.minimax.http_get",
        return_value=COOKIE_MISSING_RESPONSE,
    ):
        result = provider.fetch()
    assert result.error == "session cookie expired"


def test_http_401_maps_to_expired_cookie():
    provider = _provider()
    err = urllib.error.HTTPError(
        url="u",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,  # type: ignore[arg-type]
    )
    with patch("quota_sentinel.providers.minimax.http_get", side_effect=err):
        result = provider.fetch()
    assert result.error == "session cookie expired"


def test_other_api_error_is_surfaced():
    provider = _provider()
    payload = {"base_resp": {"status_code": 2049, "status_msg": "invalid group"}}
    with patch("quota_sentinel.providers.minimax.http_get", return_value=payload):
        result = provider.fetch()
    assert result.error == "API: invalid group"


# ── Credential merging (cookie sharing across clients) ────────────────────


def test_merge_credentials_adopts_cookie_when_empty():
    empty = MiniMaxUsageProvider(api_token="sk-cp-x", group_id="g", session_cookie="")
    holder = MiniMaxUsageProvider(
        api_token="sk-cp-x", group_id="g", session_cookie="from-browser"
    )

    empty.merge_credentials_from(holder)

    assert empty.session_cookie == "from-browser"


def test_merge_credentials_keeps_own_cookie_when_present():
    fresh = MiniMaxUsageProvider(
        api_token="sk-cp-x", group_id="g", session_cookie="mine"
    )
    stale = MiniMaxUsageProvider(
        api_token="sk-cp-x", group_id="g", session_cookie="theirs"
    )

    fresh.merge_credentials_from(stale)

    assert fresh.session_cookie == "mine"


def test_merge_credentials_no_op_when_other_is_empty():
    self_ = MiniMaxUsageProvider(api_token="sk-cp-x", group_id="g", session_cookie="")
    peer = MiniMaxUsageProvider(api_token="sk-cp-x", group_id="g", session_cookie="")

    self_.merge_credentials_from(peer)

    assert self_.session_cookie == ""


# ── Factory ───────────────────────────────────────────────────────────────


def test_create_provider_passes_session_cookie():
    provider = create_provider(
        "minimax",
        {"key": "sk-cp-x", "group_id": "g", "session_cookie": "abc"},
    )
    assert isinstance(provider, MiniMaxUsageProvider)
    assert provider.api_token == "sk-cp-x"
    assert provider.group_id == "g"
    assert provider.session_cookie == "abc"
