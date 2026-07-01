"""Tests for the Alibaba Model Studio Token Plan (Team Edition) provider."""

from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from quota_sentinel.providers.alibaba_token_plan import (
    AlibabaTokenPlanUsageProvider,
    _to_float,
)

# Real response shape captured 2026-07-01 from the intl console
# (GetSubscriptionSummary). Values come back as STRINGS; the seat plan lives
# under ``data.Data`` with Total/Surplus/Count fields.
GOOD_RESPONSE = {
    "code": "200",
    "data": {
        "RequestId": "00000000-0000-0000-0000-000000000000",
        "Message": "Successful!",
        "Data": {
            "Uid": 1234567890123456,
            "TotalSurplusValue": "180000",
            "TotalCount": 1,
            "TotalValue": "250000",
            "ProductCode": "sfm_tokenplanteams_dp_intl",
        },
        "Code": "Success",
        "Success": True,
    },
}

PATCH = "quota_sentinel.providers.alibaba_token_plan.http_post_form"


def _provider(**kw):
    kw.setdefault("session_cookie", "ck=1")
    kw.setdefault("sec_token", "tok")
    return AlibabaTokenPlanUsageProvider(**kw)


def test_to_float_variants():
    assert _to_float(None) is None
    assert _to_float("12.5") == 12.5
    assert _to_float(7) == 7.0
    assert _to_float("nope") is None


def test_fetch_requires_session_cookie():
    result = AlibabaTokenPlanUsageProvider(session_cookie="", sec_token="t").fetch()
    assert result.error == "no session_cookie"
    assert result.windows == {}


SCRAPE = "quota_sentinel.providers.alibaba_token_plan.http_get_text"


def test_fetch_no_sec_token_when_scrape_empty():
    p = AlibabaTokenPlanUsageProvider(session_cookie="ck=1", sec_token="")
    with patch(SCRAPE, return_value="<html>nothing here</html>"):
        result = p.fetch()
    assert result.error == "no sec_token"


def test_fetch_scrapes_sec_token_and_passes_it():
    p = AlibabaTokenPlanUsageProvider(session_cookie="ck=1", sec_token="")
    html = 'foo({ SEC_TOKEN: "ScrapedTok_123" }) bar'
    with (
        patch(SCRAPE, return_value=html),
        patch(PATCH, return_value=GOOD_RESPONSE) as post,
    ):
        result = p.fetch()
    assert result.error is None
    assert result.windows["credits"].utilization == pytest.approx(28.0)
    # the scraped token must reach the POST form body (positional arg 1)
    fields = post.call_args.args[1]
    assert fields["sec_token"] == "ScrapedTok_123"


def test_pinned_sec_token_skips_scrape():
    p = AlibabaTokenPlanUsageProvider(session_cookie="ck=1", sec_token="pinned")
    with (
        patch(SCRAPE, side_effect=AssertionError("should not scrape")),
        patch(PATCH, return_value=GOOD_RESPONSE) as post,
    ):
        result = p.fetch()
    assert result.error is None
    assert post.call_args.args[1]["sec_token"] == "pinned"


def test_fetch_parses_credits():
    with patch(PATCH, return_value=GOOD_RESPONSE):
        result = _provider().fetch()

    assert result.error is None
    assert set(result.windows) == {"credits"}
    w = result.windows["credits"]
    # used = 250000 - 180000 = 70000 → 28%
    assert w.utilization == pytest.approx(28.0)
    assert w.metadata is not None
    assert w.metadata["total_credits"] == 250000
    assert w.metadata["remaining_credits"] == 180000
    assert w.metadata["used_credits"] == 70000


def test_fetch_full_seat_is_zero_utilization():
    """A fresh seat (Surplus == Total) reads as 0% used, not an error."""
    resp = {
        "code": "200",
        "data": {"Data": {"TotalValue": "25000", "TotalSurplusValue": "25000"}},
    }
    with patch(PATCH, return_value=resp):
        result = _provider().fetch()
    assert result.error is None
    assert result.windows["credits"].utilization == pytest.approx(0.0)


def test_fetch_console_need_login():
    with patch(PATCH, return_value={"code": "ConsoleNeedLogin"}):
        result = _provider().fetch()
    assert result.error == "ConsoleNeedLogin"


def test_fetch_stale_sec_token_envelope():
    """Missing/stale sec_token comes back as a 200 envelope, not an HTTP 4xx."""
    with patch(PATCH, return_value={"code": "PostonlyOrTokenError"}):
        result = _provider().fetch()
    assert result.error == "sec_token expired"


def test_fetch_addon_zero_total_is_no_totals():
    """The shared-pack add-on ProductCode reads 0/0 when not purchased."""
    resp = {
        "code": "200",
        "data": {"Data": {"TotalValue": "0", "TotalSurplusValue": "0"}},
    }
    with patch(PATCH, return_value=resp):
        result = _provider().fetch()
    assert result.error == "no credit totals"


def test_fetch_http_401_maps_to_auth_failed():
    err = urllib.error.HTTPError("u", 401, "unauth", {}, None)  # type: ignore[arg-type]
    with patch(PATCH, side_effect=err):
        result = _provider().fetch()
    assert result.error == "auth failed"


def test_merge_credentials_keeps_existing_cookie():
    fresh = AlibabaTokenPlanUsageProvider(session_cookie="", sec_token="")
    old = AlibabaTokenPlanUsageProvider(session_cookie="good", sec_token="tok")
    fresh.merge_credentials_from(old)
    assert fresh.session_cookie == "good"
    assert fresh.sec_token == "tok"
