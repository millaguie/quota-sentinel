"""Tests for provider error handling."""

from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from quota_sentinel.providers.errors import (
    AuthError,
    NetworkError,
    ProviderError,
    RateLimitError,
    RetryConfig,
    TransientError,
    retry_with_backoff,
)


class TestRetryConfig:
    """RetryConfig dataclass tests."""

    def test_default_values(self):
        """Test default retry configuration."""
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.retry_on_timeout is True

    def test_custom_values(self):
        """Test custom retry configuration."""
        config = RetryConfig(max_attempts=5, base_delay=2.0, max_delay=120.0)
        assert config.max_attempts == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 120.0


class TestProviderError:
    """ProviderError exception tests."""

    def test_str_representation(self):
        """Test string representation of ProviderError."""
        err = ProviderError("test error", provider="test")
        assert str(err) == "test error"
        assert err.provider == "test"

    def test_is_runtime_error(self):
        """Test that ProviderError is a RuntimeError."""
        err = ProviderError("test")
        assert isinstance(err, RuntimeError)


class TestAuthError:
    """AuthError exception tests."""

    def test_is_provider_error(self):
        """Test that AuthError is a ProviderError."""
        err = AuthError(provider="test")
        assert isinstance(err, ProviderError)


class TestRateLimitError:
    """RateLimitError exception tests."""

    def test_is_provider_error(self):
        """Test that RateLimitError is a ProviderError."""
        err = RateLimitError(provider="test")
        assert isinstance(err, ProviderError)


class TestTransientError:
    """TransientError exception tests."""

    def test_is_provider_error(self):
        """Test that TransientError is a ProviderError."""
        err = TransientError(provider="test")
        assert isinstance(err, ProviderError)


class TestNetworkError:
    """NetworkError exception tests."""

    def test_is_provider_error(self):
        """Test that NetworkError is a ProviderError."""
        err = NetworkError(provider="test")
        assert isinstance(err, ProviderError)


class TestRetryWithBackoff:
    """retry_with_backoff decorator tests."""

    def test_successful_call_no_retries(self):
        """Test successful call doesn't trigger retries."""
        mock_func = MagicMock(return_value="success")

        @retry_with_backoff(RetryConfig(max_attempts=3))
        def func():
            return mock_func()

        result = func()
        assert result == "success"
        assert mock_func.call_count == 1

    def test_retries_on_transient_error(self):
        """Test retry on transient HTTP error (500)."""
        call_count = 0

        @retry_with_backoff(RetryConfig(max_attempts=3, base_delay=0.01))
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise urllib.error.HTTPError(
                    url="http://x", code=500, msg="Server Error", hdrs={}, fp=None
                )
            return "success"

        result = func()
        assert result == "success"
        assert call_count == 3

    def test_retries_on_timeout(self):
        """Test retry on timeout (HTTP 599)."""
        call_count = 0

        @retry_with_backoff(RetryConfig(max_attempts=3, base_delay=0.01))
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise urllib.error.HTTPError(
                    url="http://x", code=599, msg="Timeout", hdrs={}, fp=None
                )
            return "success"

        result = func()
        assert result == "success"
        assert call_count == 2

    def test_does_not_retry_on_auth_error(self):
        """Test that auth errors are not retried."""
        mock_func = MagicMock()

        @retry_with_backoff(RetryConfig(max_attempts=3))
        def func():
            mock_func()
            raise AuthError(provider="test")

        with pytest.raises(AuthError):
            func()
        assert mock_func.call_count == 1

    def test_does_not_retry_on_rate_limit(self):
        """Test that rate limit errors are not retried (caller should back off)."""
        mock_func = MagicMock()

        @retry_with_backoff(RetryConfig(max_attempts=3))
        def func():
            mock_func()
            raise RateLimitError(provider="test")

        with pytest.raises(RateLimitError):
            func()
        assert mock_func.call_count == 1

    def test_raises_after_max_attempts(self):
        """Test that errors are raised after max attempts."""

        @retry_with_backoff(RetryConfig(max_attempts=3, base_delay=0.01))
        def func():
            raise urllib.error.HTTPError(
                url="http://x", code=500, msg="Server Error", hdrs={}, fp=None
            )

        with pytest.raises(TransientError) as exc_info:
            func()
        assert "Server Error" in str(exc_info.value)

    def test_retry_on_network_error(self):
        """Test retry on network errors (URLError)."""
        call_count = 0

        @retry_with_backoff(RetryConfig(max_attempts=3, base_delay=0.01))
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise urllib.error.URLError("Connection refused")
            return "success"

        result = func()
        assert result == "success"
        assert call_count == 2

    def test_no_retry_when_max_attempts_is_1(self):
        """Test that no retries happen when max_attempts=1."""
        mock_func = MagicMock()

        @retry_with_backoff(RetryConfig(max_attempts=1))
        def func():
            mock_func()
            raise urllib.error.HTTPError(
                url="http://x", code=500, msg="Server Error", hdrs={}, fp=None
            )

        with pytest.raises(TransientError):
            func()
        assert mock_func.call_count == 1

    def test_retry_config_respects_disabled_timeout_retry(self):
        """Test that retry_on_timeout=False disables timeout retries."""
        call_count = 0

        @retry_with_backoff(RetryConfig(max_attempts=3, retry_on_timeout=False))
        def func():
            nonlocal call_count
            call_count += 1
            raise urllib.error.HTTPError(
                url="http://x", code=599, msg="Timeout", hdrs={}, fp=None
            )

        with pytest.raises(TransientError):
            func()
        assert call_count == 1


class TestClassifyHttpError:
    """HTTP error classification tests."""

    def test_401_is_auth_error(self):
        """Test 401 is classified as AuthError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=401, msg="Unauthorized", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, AuthError)

    def test_403_is_auth_error(self):
        """Test 403 is classified as AuthError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=403, msg="Forbidden", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, AuthError)

    def test_429_is_rate_limit_error(self):
        """Test 429 is classified as RateLimitError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=429, msg="Rate Limited", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, RateLimitError)

    def test_500_is_transient_error(self):
        """Test 500 is classified as TransientError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=500, msg="Server Error", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, TransientError)

    def test_502_is_transient_error(self):
        """Test 502 is classified as TransientError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=502, msg="Bad Gateway", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, TransientError)

    def test_503_is_transient_error(self):
        """Test 503 is classified as TransientError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=503, msg="Service Unavailable", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, TransientError)

    def test_504_is_transient_error(self):
        """Test 504 is classified as TransientError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=504, msg="Gateway Timeout", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, TransientError)

    def test_599_is_transient_error(self):
        """Test 599 (timeout) is classified as TransientError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=599, msg="Timeout", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, TransientError)

    def test_unknown_code_is_transient_error(self):
        """Test unknown HTTP codes are classified as TransientError."""
        from quota_sentinel.providers.errors import classify_http_error

        error = urllib.error.HTTPError(
            url="http://x", code=418, msg="I'm a teapot", hdrs={}, fp=None
        )
        result = classify_http_error(error, provider="test")
        assert isinstance(result, TransientError)
