"""Tests for all AI provider implementations."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import UTC, datetime

from quota_sentinel.providers.alibaba import AlibabaUsageProvider
from quota_sentinel.providers.claude import ClaudeUsageProvider
from quota_sentinel.providers.copilot import CopilotUsageProvider
from quota_sentinel.providers.deepseek import DeepSeekUsageProvider
from quota_sentinel.providers.minimax import MiniMaxUsageProvider
from quota_sentinel.providers.zai import ZaiUsageProvider


# ── Alibaba ──────────────────────────────────────────────────────────────


class TestAlibabaFetch:
    """AlibabaUsageProvider.fetch() tests."""

    def test_returns_error_when_no_token(self):
        prov = AlibabaUsageProvider(api_token="")
        result = prov.fetch()
        assert result.error == "no token"

    def test_parses_response_with_direct_quota_info(self):
        """Test parsing when quota info is at top level."""
        data = {
            "code": "200",
            "data": {
                "result": {
                    "codingPlanInstanceInfos": [
                        {
                            "codingPlanQuotaInfo": {
                                "per5HourUsedQuota": 100,
                                "per5HourTotalQuota": 300,
                                "perWeekUsedQuota": 500,
                                "perWeekTotalQuota": 1000,
                                "perBillMonthUsedQuota": 2000,
                                "perBillMonthTotalQuota": 5000,
                                "per5HourQuotaNextRefreshTime": 1744329600000,
                            }
                        }
                    ]
                }
            },
        }
        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            return_value=data,
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert result.error is None
            assert "5h" in result.windows
            assert "weekly" in result.windows
            assert "monthly" in result.windows
            assert result.windows["5h"].utilization == pytest.approx(33.33, rel=0.1)

    def test_parses_response_with_nested_data(self):
        """Test parsing when data is nested under 'data' key."""
        data = {
            "data": {
                "result": {
                    "codingPlanInstanceInfos": [
                        {
                            "codingPlanQuotaInfo": {
                                "per5HourUsedQuota": 50,
                                "per5HourTotalQuota": 300,
                            }
                        }
                    ]
                }
            }
        }
        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            return_value=data,
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert result.error is None
            assert "5h" in result.windows

    def test_handles_http_error_401(self):
        """Test 401 HTTP error handling."""
        from quota_sentinel.providers.errors import AuthError

        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            side_effect=AuthError(message="Unauthorized (auth failed)"),
        ):
            prov = AlibabaUsageProvider(api_token="bad_token")
            result = prov.fetch()
            assert "auth failed" in result.error

    def test_handles_http_error_429(self):
        """Test 429 rate limit error handling."""
        from quota_sentinel.providers.errors import RateLimitError

        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            side_effect=RateLimitError(message="Rate Limited (rate limited)"),
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert "rate limited" in result.error

    def test_handles_generic_http_error(self):
        """Test generic HTTP error handling."""
        from quota_sentinel.providers.errors import TransientError

        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            side_effect=TransientError(message="Server Error (server error)"),
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert "server error" in result.error

    def test_handles_network_error(self):
        """Test network error handling."""
        from quota_sentinel.providers.errors import NetworkError

        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            side_effect=NetworkError(message="network error: Connection failed"),
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert "network error" in result.error

    def test_handles_consoleneedlogin_error(self):
        """Test ConsoleNeedLogin response code handling."""
        data = {"code": "ConsoleNeedLogin"}
        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            return_value=data,
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert result.error == "ConsoleNeedLogin"

    def test_handles_missing_quota_data(self):
        """Test response with no quota data."""
        data = {"code": "200"}
        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            return_value=data,
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert result.error == "no quota data"

    def test_cn_region_uses_cn_host(self):
        """Test that CN region uses correct host."""
        data = {
            "data": {
                "result": {
                    "codingPlanInstanceInfos": [
                        {
                            "codingPlanQuotaInfo": {
                                "per5HourUsedQuota": 0,
                                "per5HourTotalQuota": 300,
                            }
                        }
                    ]
                }
            }
        }
        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            return_value=data,
        ) as mock_post:
            prov = AlibabaUsageProvider(api_token="test_token", region="cn")
            result = prov.fetch()
            assert result.error is None
            call_args = mock_post.call_args
            assert "bailian.console.aliyun.com" in call_args[0][0]

    def test_invalidates_total_zero(self):
        """Test that windows with total=0 are skipped."""
        data = {
            "data": {
                "result": {
                    "codingPlanInstanceInfos": [
                        {
                            "codingPlanQuotaInfo": {
                                "per5HourUsedQuota": 0,
                                "per5HourTotalQuota": 0,
                                "perWeekUsedQuota": 100,
                                "perWeekTotalQuota": 1000,
                            }
                        }
                    ]
                }
            }
        }
        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            return_value=data,
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert "5h" not in result.windows
            assert "weekly" in result.windows

    def test_utilization_capped_at_100(self):
        """Test that utilization is capped at 100%."""
        data = {
            "data": {
                "result": {
                    "codingPlanInstanceInfos": [
                        {
                            "codingPlanQuotaInfo": {
                                "per5HourUsedQuota": 500,
                                "per5HourTotalQuota": 300,
                            }
                        }
                    ]
                }
            }
        }
        with patch(
            "quota_sentinel.providers.alibaba.http_post_json",
            return_value=data,
        ):
            prov = AlibabaUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert result.windows["5h"].utilization == 100.0


class TestAlibabaParseReset:
    """AlibabaUsageProvider._parse_reset() tests."""

    def test_parses_timestamp_milliseconds(self):
        """Test parsing millisecond timestamps."""
        ts = 1744329600000
        result = AlibabaUsageProvider._parse_reset(ts)
        assert result is not None
        assert result.tzinfo is not None

    def test_parses_iso_format_string(self):
        """Test parsing ISO format strings."""
        result = AlibabaUsageProvider._parse_reset("2025-04-10T12:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_parses_iso_format_without_tz(self):
        """Test parsing ISO format without timezone."""
        result = AlibabaUsageProvider._parse_reset("2025-04-10T12:00:00")
        assert result is not None

    def test_returns_none_for_invalid_input(self):
        """Test that invalid input returns None."""
        assert AlibabaUsageProvider._parse_reset("not a date") is None
        assert AlibabaUsageProvider._parse_reset(None) is None
        assert AlibabaUsageProvider._parse_reset(999999999999999) is None


class TestAlibabaFindQuota:
    """AlibabaUsageProvider._find_quota() tests."""

    def test_finds_quota_at_data_level(self):
        """Test finding quota when directly in data."""
        data = {
            "per5HourTotalQuota": 300,
            "per5HourUsedQuota": 100,
        }
        result = AlibabaUsageProvider._find_quota(data)
        assert result is not None
        assert result.get("per5HourTotalQuota") == 300

    def test_finds_quota_in_codingplaninstanceinfos(self):
        """Test finding quota in nested structure."""
        data = {
            "data": {
                "result": {
                    "codingPlanInstanceInfos": [
                        {"codingPlanQuotaInfo": {"per5HourTotalQuota": 300}}
                    ]
                }
            }
        }
        result = AlibabaUsageProvider._find_quota(data)
        assert result is not None
        assert result.get("per5HourTotalQuota") == 300

    def test_returns_none_when_not_found(self):
        """Test that non-existent quota returns None."""
        data = {"unrelated": "data"}
        result = AlibabaUsageProvider._find_quota(data)
        assert result is None


class TestAlibabaSearchQuota:
    """AlibabaUsageProvider._search_quota() tests."""

    def test_finds_quota_deep_in_structure(self):
        """Test finding quota deeply nested."""
        data = {"level1": {"level2": {"level3": {"per5HourTotalQuota": 300}}}}
        result = AlibabaUsageProvider._search_quota(data, depth=0)
        assert result is not None
        assert result.get("per5HourTotalQuota") == 300

    def test_respects_max_depth(self):
        """Test that search respects max depth."""
        data = {"l1": {"l2": {"l3": {"l4": {"l5": {"l6": "deep"}}}}}}
        result = AlibabaUsageProvider._search_quota(data, depth=5)
        assert result is None

    def test_handles_lists_in_search(self):
        """Test that search handles lists."""
        data = {
            "items": [
                None,
                {"per5HourTotalQuota": 300},
                "not a dict",
            ]
        }
        result = AlibabaUsageProvider._search_quota(data, depth=0)
        assert result is not None
        assert result.get("per5HourTotalQuota") == 300


# ── Claude ──────────────────────────────────────────────────────────────


class TestClaudeFetch:
    """ClaudeUsageProvider.fetch() tests."""

    def test_returns_error_when_no_credentials(self):
        prov = ClaudeUsageProvider(access_token="")
        result = prov.fetch()
        assert result.error == "no credentials"

    def test_returns_error_when_token_expired_and_no_refresh(self):
        """Test expired token with no refresh token."""
        prov = ClaudeUsageProvider(
            access_token="expired_token",
            refresh_token="",
            expires_at=0,
        )
        # Manually set to expired
        prov.expires_at = 0
        with patch(
            "quota_sentinel.providers.claude.http_get",
            side_effect=OSError("Should not be called"),
        ):
            result = prov.fetch()
            assert result.error == "token refresh failed"

    def test_fetches_usage_successfully(self):
        """Test successful usage fetch."""
        data = {
            "five_hour": {
                "utilization": 45.5,
                "resets_at": "2025-04-10T12:00:00Z",
            },
            "seven_day": {
                "utilization": 20.0,
                "resets_at": "2025-04-15T00:00:00Z",
            },
        }
        with patch(
            "quota_sentinel.providers.claude.http_get",
            return_value=data,
        ):
            prov = ClaudeUsageProvider(
                access_token="test_token", expires_at=9999999999999
            )
            result = prov.fetch()
            assert result.error is None
            assert "five_hour" in result.windows
            assert "seven_day" in result.windows
            assert result.windows["five_hour"].utilization == 45.5

    def test_handles_http_error_429(self):
        """Test rate limiting error."""
        from quota_sentinel.providers.errors import RateLimitError

        with patch(
            "quota_sentinel.providers.claude.http_get",
            side_effect=RateLimitError(message="Rate Limited (rate limited)"),
        ):
            prov = ClaudeUsageProvider(
                access_token="test_token", expires_at=9999999999999
            )
            result = prov.fetch()
            assert result.error is not None and "rate limited" in result.error

    def test_handles_generic_http_error(self):
        """Test generic HTTP error."""
        from quota_sentinel.providers.errors import TransientError

        with patch(
            "quota_sentinel.providers.claude.http_get",
            side_effect=TransientError(message="Server Error (server error)"),
        ):
            prov = ClaudeUsageProvider(
                access_token="test_token", expires_at=9999999999999
            )
            result = prov.fetch()
            assert result.error is not None and "server error" in result.error

    def test_handles_network_error(self):
        """Test network error."""
        from quota_sentinel.providers.errors import NetworkError

        with patch(
            "quota_sentinel.providers.claude.http_get",
            side_effect=NetworkError(message="network error: Connection refused"),
        ):
            prov = ClaudeUsageProvider(
                access_token="test_token", expires_at=9999999999999
            )
            result = prov.fetch()
            assert result.error is not None and "network error" in result.error

    def test_handles_invalid_resets_at_format(self):
        """Test handling of invalid resets_at format."""
        data = {
            "five_hour": {
                "utilization": 50.0,
                "resets_at": "not a valid date",
            },
        }
        with patch(
            "quota_sentinel.providers.claude.http_get",
            return_value=data,
        ):
            prov = ClaudeUsageProvider(
                access_token="test_token", expires_at=9999999999999
            )
            result = prov.fetch()
            assert result.error is None
            assert result.windows["five_hour"].resets_at is None

    def test_skips_missing_buckets(self):
        """Test that missing bucket data is skipped."""
        data = {
            "five_hour": {"utilization": 50.0},
        }
        with patch(
            "quota_sentinel.providers.claude.http_get",
            return_value=data,
        ):
            prov = ClaudeUsageProvider(
                access_token="test_token", expires_at=9999999999999
            )
            result = prov.fetch()
            assert result.error is None
            assert "five_hour" in result.windows
            assert "seven_day" not in result.windows


class TestClaudeRefresh:
    """ClaudeUsageProvider._refresh() tests."""

    def test_returns_false_when_no_refresh_token(self):
        """Test that refresh returns False with no refresh token."""
        prov = ClaudeUsageProvider(access_token="token", refresh_token="")
        result = prov._refresh()
        assert result is False

    def test_successful_token_refresh(self):
        """Test successful token refresh."""
        refresh_data = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
        }
        with patch(
            "quota_sentinel.providers.claude.http_post_json",
            return_value=refresh_data,
        ):
            prov = ClaudeUsageProvider(
                access_token="old_token",
                refresh_token="refresh_token",
                expires_at=0,
            )
            result = prov._refresh()
            assert result is True
            assert prov.access_token == "new_access_token"
            assert prov.refresh_token == "new_refresh_token"
            assert prov.expires_at > 0

    def test_refresh_handles_error(self):
        """Test refresh error handling."""
        with patch(
            "quota_sentinel.providers.claude.http_post_json",
            side_effect=OSError("Refresh failed"),
        ):
            prov = ClaudeUsageProvider(
                access_token="token",
                refresh_token="refresh",
            )
            result = prov._refresh()
            assert result is False


class TestClaudeCurrentCredentials:
    """ClaudeUsageProvider.current_credentials() tests."""

    def test_returns_current_credentials(self):
        """Test that credentials are returned correctly."""
        prov = ClaudeUsageProvider(
            access_token="access",
            refresh_token="refresh",
            expires_at=1234567890000,
        )
        creds = prov.current_credentials()
        assert creds["access_token"] == "access"
        assert creds["refresh_token"] == "refresh"
        assert creds["expires_at"] == 1234567890000


# ── Copilot ─────────────────────────────────────────────────────────────


class TestCopilotFetch:
    """CopilotUsageProvider.fetch() tests."""

    def test_returns_error_when_no_token(self):
        prov = CopilotUsageProvider(github_token="", github_username="user")
        result = prov.fetch()
        assert result.error == "no token"

    def test_returns_error_when_no_username(self):
        prov = CopilotUsageProvider(github_token="token", github_username="")
        result = prov.fetch()
        assert result.error == "no username"

    def test_fetches_usage_successfully(self):
        """Test successful usage fetch."""
        data = {
            "usageItems": [
                {"grossQuantity": 100},
                {"grossQuantity": 50},
            ]
        }
        with patch(
            "quota_sentinel.providers.copilot.http_get",
            return_value=data,
        ):
            prov = CopilotUsageProvider(
                github_token="token",
                github_username="user",
                plan="pro",
            )
            result = prov.fetch()
            assert result.error is None
            assert "monthly" in result.windows
            # 150 / 300 * 100 = 50%
            assert result.windows["monthly"].utilization == 50.0

    def test_handles_http_error_401(self):
        """Test 401 error handling."""
        from quota_sentinel.providers.errors import AuthError

        with patch(
            "quota_sentinel.providers.copilot.http_get",
            side_effect=AuthError(message="Unauthorized (auth failed)"),
        ):
            prov = CopilotUsageProvider(github_token="bad", github_username="user")
            result = prov.fetch()
            assert result.error is not None and "auth failed" in result.error

    def test_handles_http_error_403(self):
        """Test 403 error handling."""
        from quota_sentinel.providers.errors import AuthError

        with patch(
            "quota_sentinel.providers.copilot.http_get",
            side_effect=AuthError(message="Forbidden (auth failed)"),
        ):
            prov = CopilotUsageProvider(github_token="token", github_username="user")
            result = prov.fetch()
            assert result.error is not None and "auth failed" in result.error

    def test_handles_http_error_429(self):
        """Test rate limiting error."""
        from quota_sentinel.providers.errors import RateLimitError

        with patch(
            "quota_sentinel.providers.copilot.http_get",
            side_effect=RateLimitError(message="Rate Limited (rate limited)"),
        ):
            prov = CopilotUsageProvider(github_token="token", github_username="user")
            result = prov.fetch()
            assert result.error is not None and "rate limited" in result.error

    def test_handles_network_error(self):
        """Test network error."""
        from quota_sentinel.providers.errors import NetworkError

        with patch(
            "quota_sentinel.providers.copilot.http_get",
            side_effect=NetworkError(message="network error: Connection failed"),
        ):
            prov = CopilotUsageProvider(github_token="token", github_username="user")
            result = prov.fetch()
            assert result.error is not None and "network error" in result.error

    def test_empty_usage_items(self):
        """Test handling of empty usage items."""
        data = {"usageItems": []}
        with patch(
            "quota_sentinel.providers.copilot.http_get",
            return_value=data,
        ):
            prov = CopilotUsageProvider(
                github_token="token",
                github_username="user",
            )
            result = prov.fetch()
            assert result.error is None
            assert result.windows["monthly"].utilization == 0.0

    def test_utilization_capped_at_100(self):
        """Test that utilization is capped at 100%."""
        data = {
            "usageItems": [
                {"grossQuantity": 1000},
                {"grossQuantity": 500},
            ]
        }
        with patch(
            "quota_sentinel.providers.copilot.http_get",
            return_value=data,
        ):
            prov = CopilotUsageProvider(
                github_token="token",
                github_username="user",
                plan="free",  # 50 limit
            )
            result = prov.fetch()
            assert result.windows["monthly"].utilization == 100.0


class TestCopilotPlanAllowances:
    """CopilotUsageProvider plan allowance tests."""

    def test_free_plan_allowance(self):
        """Test free plan has 50 allowance."""
        prov = CopilotUsageProvider(
            github_token="token",
            github_username="user",
            plan="free",
        )
        assert prov.allowance == 50

    def test_pro_plan_allowance(self):
        """Test pro plan has 300 allowance."""
        prov = CopilotUsageProvider(
            github_token="token",
            github_username="user",
            plan="pro",
        )
        assert prov.allowance == 300

    def test_pro_plus_plan_allowance(self):
        """Test pro_plus plan has 1500 allowance."""
        prov = CopilotUsageProvider(
            github_token="token",
            github_username="user",
            plan="pro_plus",
        )
        assert prov.allowance == 1500

    def test_numeric_plan_allowance(self):
        """Test numeric plan string is converted to int."""
        prov = CopilotUsageProvider(
            github_token="token",
            github_username="user",
            plan="500",
        )
        assert prov.allowance == 500

    def test_invalid_plan_defaults_to_300(self):
        """Test invalid plan defaults to 300."""
        prov = CopilotUsageProvider(
            github_token="token",
            github_username="user",
            plan="invalid",
        )
        assert prov.allowance == 300


# ── DeepSeek ─────────────────────────────────────────────────────────────


class TestDeepSeekFetch:
    """DeepSeekUsageProvider.fetch() tests."""

    def test_returns_error_when_no_token(self):
        prov = DeepSeekUsageProvider(api_token="")
        result = prov.fetch()
        assert result.error == "no token"

    def test_fetches_balance_successfully(self):
        """Test successful balance fetch."""
        data = {
            "balance_infos": [
                {
                    "total_balance": "50.00",
                    "currency": "USD",
                }
            ],
            "is_available": True,
        }
        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            return_value=data,
        ):
            prov = DeepSeekUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert result.error is None
            assert "balance" in result.windows
            # First call: ref = 50, pct = 100 - (50/50*100) = 0%
            # Actually: pct = max(0, 100 - (50/50*100)) = max(0, 0) = 0%

    def test_handles_http_error_401(self):
        """Test 401 error handling."""
        from quota_sentinel.providers.errors import AuthError

        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            side_effect=AuthError(message="Unauthorized (auth failed)"),
        ):
            prov = DeepSeekUsageProvider(api_token="bad")
            result = prov.fetch()
            assert result.error is not None and "auth failed" in result.error

    def test_handles_http_error_429(self):
        """Test rate limiting."""
        from quota_sentinel.providers.errors import RateLimitError

        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            side_effect=RateLimitError(message="Rate Limited (rate limited)"),
        ):
            prov = DeepSeekUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.error is not None and "rate limited" in result.error

    def test_handles_network_error(self):
        """Test network error."""
        from quota_sentinel.providers.errors import NetworkError

        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            side_effect=NetworkError(message="network error: Connection refused"),
        ):
            prov = DeepSeekUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.error is not None and "network error" in result.error

    def test_handles_empty_balances(self):
        """Test empty balance list."""
        data = {"balance_infos": []}
        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            return_value=data,
        ):
            prov = DeepSeekUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.error == "no balance data"

    def test_sets_100_percent_when_unavailable(self):
        """Test that unavailable sets utilization to 100%."""
        data = {
            "balance_infos": [{"total_balance": "50.00", "currency": "USD"}],
            "is_available": False,
        }
        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            return_value=data,
        ):
            prov = DeepSeekUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.windows["balance"].utilization == 100.0

    def test_includes_metadata(self):
        """Test that metadata is included in result."""
        data = {
            "balance_infos": [{"total_balance": "75.00", "currency": "CNY"}],
            "is_available": True,
        }
        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            return_value=data,
        ):
            prov = DeepSeekUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.windows["balance"].metadata["total_balance"] == 75.00
            assert result.windows["balance"].metadata["currency"] == "CNY"
            assert result.windows["balance"].metadata["is_available"] is True


class TestDeepSeekReferenceBalance:
    """DeepSeekUsageProvider reference balance tests."""

    def test_uses_provided_reference_balance(self):
        """Test that provided reference balance is used."""
        data = {
            "balance_infos": [{"total_balance": "25.00", "currency": "USD"}],
            "is_available": True,
        }
        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            return_value=data,
        ):
            prov = DeepSeekUsageProvider(
                api_token="token",
                reference_balance=100.0,
            )
            result = prov.fetch()
            # pct = max(0, 100 - (25/100*100)) = 75%
            assert result.windows["balance"].utilization == 75.0

    def test_stores_reference_balance_after_first_fetch(self):
        """Test that reference balance is stored after first fetch."""
        data = {
            "balance_infos": [{"total_balance": "80.00", "currency": "USD"}],
            "is_available": True,
        }
        with patch(
            "quota_sentinel.providers.deepseek.http_get",
            return_value=data,
        ):
            prov = DeepSeekUsageProvider(api_token="token")
            # First fetch - ref = 80
            prov.fetch()
            assert prov._ref_balance == 80.0


# ── MiniMax ──────────────────────────────────────────────────────────────


class TestMiniMaxFetch:
    """MiniMaxUsageProvider.fetch() tests."""

    def test_returns_error_when_no_token(self):
        prov = MiniMaxUsageProvider(api_token="", group_id="group")
        result = prov.fetch()
        assert result.error == "no token"

    def test_returns_error_when_no_group_id(self):
        prov = MiniMaxUsageProvider(api_token="token", group_id="")
        result = prov.fetch()
        assert result.error == "no group_id"

    def test_fetches_usage_successfully(self):
        """Test successful usage fetch."""
        data = {
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "model_remains": [
                {
                    "model_name": "MiniMax-Text",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 20,
                    "remains_time": 3600000,
                    "current_weekly_total_count": 1000,
                    "current_weekly_usage_count": 100,
                    "weekly_remains_time": 86400000,
                },
                {
                    "model_name": "hailuo-video",
                    "current_interval_total_count": 50,
                    "current_interval_usage_count": 10,
                    "remains_time": 1800000,
                },
            ],
        }
        with patch(
            "quota_sentinel.providers.minimax.http_get",
            return_value=data,
        ):
            prov = MiniMaxUsageProvider(api_token="token", group_id="group123")
            result = prov.fetch()
            assert result.error is None
            # hailuo-video should be skipped (excluded by keyword)
            # Only MiniMax-Text should appear
            window_names = list(result.windows.keys())
            assert any("MM-Text" in w for w in window_names)

    def test_handles_http_error_401(self):
        """Test 401 error handling."""
        from quota_sentinel.providers.errors import AuthError

        with patch(
            "quota_sentinel.providers.minimax.http_get",
            side_effect=AuthError(message="Unauthorized (auth failed)"),
        ):
            prov = MiniMaxUsageProvider(api_token="bad", group_id="group")
            result = prov.fetch()
            assert result.error is not None and "auth failed" in result.error

    def test_handles_http_error_429(self):
        """Test rate limiting."""
        from quota_sentinel.providers.errors import RateLimitError

        with patch(
            "quota_sentinel.providers.minimax.http_get",
            side_effect=RateLimitError(message="Rate Limited (rate limited)"),
        ):
            prov = MiniMaxUsageProvider(api_token="token", group_id="group")
            result = prov.fetch()
            assert result.error is not None and "rate limited" in result.error

    def test_handles_network_error(self):
        """Test network error."""
        from quota_sentinel.providers.errors import NetworkError

        with patch(
            "quota_sentinel.providers.minimax.http_get",
            side_effect=NetworkError(message="network error: Connection failed"),
        ):
            prov = MiniMaxUsageProvider(api_token="token", group_id="group")
            result = prov.fetch()
            assert result.error is not None and "network error" in result.error

    def test_handles_nonzero_status_code(self):
        """Test non-zero status code error handling."""
        data = {
            "base_resp": {"status_code": 1, "status_msg": "API Error"},
        }
        with patch(
            "quota_sentinel.providers.minimax.http_get",
            return_value=data,
        ):
            prov = MiniMaxUsageProvider(api_token="token", group_id="group")
            result = prov.fetch()
            assert result.error == "API: API Error"

    def test_skips_excluded_model_types(self):
        """Test that hailuo, speech, music, image, video, audio models are skipped."""
        data = {
            "base_resp": {"status_code": 0},
            "model_remains": [
                {
                    "model_name": "hailuo-video",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 50,
                },
                {
                    "model_name": "speech-to-text",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 50,
                },
                {
                    "model_name": "music-gen",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 50,
                },
                {
                    "model_name": "image-gen",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 50,
                },
                {
                    "model_name": "video-gen",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 50,
                },
                {
                    "model_name": "audio-gen",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 50,
                },
                {
                    "model_name": "MiniMax-Text",
                    "current_interval_total_count": 100,
                    "current_interval_usage_count": 50,
                    "current_weekly_total_count": 1000,
                    "current_weekly_usage_count": 100,
                },
            ],
        }
        with patch(
            "quota_sentinel.providers.minimax.http_get",
            return_value=data,
        ):
            prov = MiniMaxUsageProvider(api_token="token", group_id="group")
            result = prov.fetch()
            window_names = list(result.windows.keys())
            # Only MiniMax-Text should appear (2 windows: interval + weekly)
            assert len(window_names) == 2
            assert "MM-Text_interval" in window_names
            assert "MM-Text_weekly" in window_names

    def test_empty_model_remains(self):
        """Test empty model_remains list."""
        data = {
            "base_resp": {"status_code": 0},
            "model_remains": [],
        }
        with patch(
            "quota_sentinel.providers.minimax.http_get",
            return_value=data,
        ):
            prov = MiniMaxUsageProvider(api_token="token", group_id="group")
            result = prov.fetch()
            assert result.error is None
            assert len(result.windows) == 0


class TestMiniMaxResetTime:
    """MiniMaxUsageProvider._reset_time() tests."""

    def test_parses_positive_remain_ms(self):
        """Test parsing of positive remain_ms."""
        result = MiniMaxUsageProvider._reset_time(3600000)
        assert result is not None
        assert result.tzinfo is not None

    def test_returns_none_for_zero(self):
        """Test that zero returns None."""
        assert MiniMaxUsageProvider._reset_time(0) is None

    def test_returns_none_for_negative(self):
        """Test that negative returns None."""
        assert MiniMaxUsageProvider._reset_time(-1000) is None


# ── Z.ai ────────────────────────────────────────────────────────────────


class TestZaiFetch:
    """ZaiUsageProvider.fetch() tests."""

    def test_returns_error_when_no_token(self):
        prov = ZaiUsageProvider(api_token="")
        result = prov.fetch()
        assert result.error == "no token"

    def test_fetches_usage_successfully(self):
        """Test successful usage fetch."""
        data = {
            "success": True,
            "data": {
                "limits": [
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 3,
                        "number": "5",
                        "percentage": 45.5,
                        "nextResetTime": 1744329600000,
                    },
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 5,
                        "number": "10",
                        "percentage": 20.0,
                    },
                ]
            },
        }
        with patch(
            "quota_sentinel.providers.zai.http_get",
            return_value=data,
        ):
            prov = ZaiUsageProvider(api_token="test_token")
            result = prov.fetch()
            assert result.error is None
            assert "5hours" in result.windows
            assert "10mcp" in result.windows

    def test_handles_http_error_401(self):
        """Test 401 error handling."""
        from quota_sentinel.providers.errors import AuthError

        with patch(
            "quota_sentinel.providers.zai.http_get",
            side_effect=AuthError(message="Unauthorized (auth failed)"),
        ):
            prov = ZaiUsageProvider(api_token="bad")
            result = prov.fetch()
            assert result.error is not None and "auth failed" in result.error

    def test_handles_http_error_429(self):
        """Test rate limiting."""
        from quota_sentinel.providers.errors import RateLimitError

        with patch(
            "quota_sentinel.providers.zai.http_get",
            side_effect=RateLimitError(message="Rate Limited (rate limited)"),
        ):
            prov = ZaiUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.error is not None and "rate limited" in result.error

    def test_handles_network_error(self):
        """Test network error."""
        from quota_sentinel.providers.errors import NetworkError

        with patch(
            "quota_sentinel.providers.zai.http_get",
            side_effect=NetworkError(message="network error: Connection refused"),
        ):
            prov = ZaiUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.error is not None and "network error" in result.error

    def test_handles_success_false(self):
        """Test success=false response."""
        data = {"success": False}
        with patch(
            "quota_sentinel.providers.zai.http_get",
            return_value=data,
        ):
            prov = ZaiUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.error == "API returned success=false"

    def test_skips_non_tokens_limits(self):
        """Test that non-TOKENS_LIMIT types are skipped."""
        data = {
            "success": True,
            "data": {
                "limits": [
                    {"type": "OTHER_LIMIT", "unit": 3, "number": "5", "percentage": 50},
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 6,
                        "number": "7",
                        "percentage": 30,
                    },
                ]
            },
        }
        with patch(
            "quota_sentinel.providers.zai.http_get",
            return_value=data,
        ):
            prov = ZaiUsageProvider(api_token="token")
            result = prov.fetch()
            window_names = list(result.windows.keys())
            assert "7days" in window_names
            assert "5hours" not in window_names

    def test_handles_missing_next_reset_time(self):
        """Test handling of missing nextResetTime."""
        data = {
            "success": True,
            "data": {
                "limits": [
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 3,
                        "number": "5",
                        "percentage": 50,
                    },
                ]
            },
        }
        with patch(
            "quota_sentinel.providers.zai.http_get",
            return_value=data,
        ):
            prov = ZaiUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.windows["5hours"].resets_at is None

    def test_handles_invalid_reset_time(self):
        """Test handling of invalid reset time."""
        data = {
            "success": True,
            "data": {
                "limits": [
                    {
                        "type": "TOKENS_LIMIT",
                        "unit": 3,
                        "number": "5",
                        "percentage": 50,
                        "nextResetTime": 999999999999999,
                    },
                ]
            },
        }
        with patch(
            "quota_sentinel.providers.zai.http_get",
            return_value=data,
        ):
            prov = ZaiUsageProvider(api_token="token")
            result = prov.fetch()
            assert result.windows["5hours"].resets_at is None


class TestZaiUnitMap:
    """Z.ai unit map tests."""

    def test_unit_map_values(self):
        """Test known unit map values."""
        from quota_sentinel.providers.zai import _ZAI_UNIT_MAP

        assert _ZAI_UNIT_MAP[3] == "hours"
        assert _ZAI_UNIT_MAP[5] == "mcp"
        assert _ZAI_UNIT_MAP[6] == "days"
