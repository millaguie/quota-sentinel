"""Tests for http helper module."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

from quota_sentinel.providers.http import http_get, http_post_json


@contextmanager
def mock_urlopen_success(return_data: dict):
    """Create a mock urlopen that returns success with the given data."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(return_data).encode()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_response
    mock_cm.__exit__.return_value = None
    yield mock_cm


class TestHttpGet:
    """Tests for http_get function."""

    def test_constructs_request_with_user_agent(self):
        """Test that User-Agent header is set."""
        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = http_get(
                "https://example.com/api", {"Authorization": "Bearer token"}
            )

            # Verify the request was constructed with User-Agent
            mock_urlopen.assert_called_once()
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            # Note: headers are case-insensitive, urllib normalizes to User-agent
            assert "User-agent" in request.headers or "User-Agent" in request.headers

    def test_get_request_method(self):
        """Test that GET method is used."""
        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = http_get("https://example.com/api", {})

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.method == "GET"

    def test_returns_parsed_json(self):
        """Test that JSON response is parsed."""
        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = http_get("https://example.com/api", {})

            assert result == {"key": "value"}


class TestHttpPostJson:
    """Tests for http_post_json function."""

    def test_constructs_post_request(self):
        """Test that POST method is used."""
        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"status": "ok"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = http_post_json("https://example.com/api", {"key": "value"})

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.method == "POST"

    def test_sets_content_type_header(self):
        """Test that Content-Type is set to application/json."""
        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"status": "ok"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = http_post_json("https://example.com/api", {"key": "value"})

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.headers.get("Content-type") == "application/json"

    def test_encodes_body_as_json(self):
        """Test that body is JSON encoded."""
        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"status": "ok"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = http_post_json("https://example.com/api", {"key": "value"})

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            # Verify the data was encoded
            assert request.data == b'{"key": "value"}'

    def test_returns_parsed_json_response(self):
        """Test that response JSON is parsed."""
        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"result": "success"}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = http_post_json("https://example.com/api", {})

            assert result == {"result": "success"}


class TestHttpGetRetry:
    """Tests for http_get retry behavior."""

    def test_retries_on_http_500_and_succeeds(self):
        """Test that HTTP 500 triggers retry and eventual success."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            # Create a proper mock context manager
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = mock_response
            mock_cm.__exit__.return_value = None

            # First call fails with 500, second succeeds
            mock_urlopen.side_effect = [
                urllib.error.HTTPError(
                    url="http://x", code=500, msg="Server Error", hdrs={}, fp=None
                ),
                mock_cm,
            ]

            result = http_get(
                "https://example.com/api",
                {},
                max_attempts=3,
                base_delay=0.01,
            )

            assert result == {"key": "value"}
            assert mock_urlopen.call_count == 2

    def test_raises_auth_error_on_http_401_no_retry(self):
        """Test that HTTP 401 raises AuthError without retry."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="http://x", code=401, msg="Unauthorized", hdrs={}, fp=None
            )

            from quota_sentinel.providers.errors import AuthError

            with pytest.raises(AuthError):
                http_get("https://example.com/api", {}, max_attempts=3)

            assert mock_urlopen.call_count == 1

    def test_raises_rate_limit_error_on_http_429_no_retry(self):
        """Test that HTTP 429 raises RateLimitError without retry."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="http://x", code=429, msg="Rate Limited", hdrs={}, fp=None
            )

            from quota_sentinel.providers.errors import RateLimitError

            with pytest.raises(RateLimitError):
                http_get("https://example.com/api", {}, max_attempts=3)

            assert mock_urlopen.call_count == 1

    def test_retries_on_urlerror_network_error(self):
        """Test that URLError triggers retry."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = mock_response
            mock_cm.__exit__.return_value = None

            # First call fails with URLError, second succeeds
            mock_urlopen.side_effect = [
                urllib.error.URLError("Connection refused"),
                mock_cm,
            ]

            result = http_get(
                "https://example.com/api",
                {},
                max_attempts=3,
                base_delay=0.01,
            )

            assert result == {"key": "value"}
            assert mock_urlopen.call_count == 2

    def test_raises_transient_error_after_max_attempts(self):
        """Test that TransientError is raised after max attempts."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="http://x", code=500, msg="Server Error", hdrs={}, fp=None
            )

            from quota_sentinel.providers.errors import TransientError

            with pytest.raises(TransientError):
                http_get(
                    "https://example.com/api",
                    {},
                    max_attempts=3,
                    base_delay=0.01,
                )

            assert mock_urlopen.call_count == 3

    def test_retries_on_http_502(self):
        """Test that HTTP 502 triggers retry."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'

            # Create context manager mock
            mock_success = MagicMock()
            mock_success.__enter__.return_value = mock_response
            mock_success.__exit__.return_value = None

            # First call raises, second returns success context manager
            mock_urlopen.side_effect = [
                urllib.error.HTTPError(
                    url="http://x", code=502, msg="Bad Gateway", hdrs={}, fp=None
                ),
                mock_success,
            ]

            result = http_get(
                "https://example.com/api",
                {},
                max_attempts=3,
                base_delay=0.01,
            )

            assert result == {"key": "value"}
            assert mock_urlopen.call_count == 2

    def test_retries_on_http_503(self):
        """Test that HTTP 503 triggers retry."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'

            mock_success = MagicMock()
            mock_success.__enter__.return_value = mock_response
            mock_success.__exit__.return_value = None

            mock_urlopen.side_effect = [
                urllib.error.HTTPError(
                    url="http://x",
                    code=503,
                    msg="Service Unavailable",
                    hdrs={},
                    fp=None,
                ),
                mock_success,
            ]

            result = http_get(
                "https://example.com/api",
                {},
                max_attempts=3,
                base_delay=0.01,
            )

            assert result == {"key": "value"}
            assert mock_urlopen.call_count == 2

    def test_retries_on_http_504(self):
        """Test that HTTP 504 triggers retry."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'

            mock_success = MagicMock()
            mock_success.__enter__.return_value = mock_response
            mock_success.__exit__.return_value = None

            mock_urlopen.side_effect = [
                urllib.error.HTTPError(
                    url="http://x", code=504, msg="Gateway Timeout", hdrs={}, fp=None
                ),
                mock_success,
            ]

            result = http_get(
                "https://example.com/api",
                {},
                max_attempts=3,
                base_delay=0.01,
            )

            assert result == {"key": "value"}
            assert mock_urlopen.call_count == 2


class TestHttpPostJsonRetry:
    """Tests for http_post_json retry behavior."""

    def test_retries_on_http_500_and_succeeds(self):
        """Test that HTTP 500 triggers retry and eventual success."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = mock_response
            mock_cm.__exit__.return_value = None

            mock_urlopen.side_effect = [
                urllib.error.HTTPError(
                    url="http://x", code=500, msg="Server Error", hdrs={}, fp=None
                ),
                mock_cm,
            ]

            result = http_post_json(
                "https://example.com/api",
                {"data": "test"},
                max_attempts=3,
                base_delay=0.01,
            )

            assert result == {"key": "value"}
            assert mock_urlopen.call_count == 2

    def test_raises_auth_error_on_http_403_no_retry(self):
        """Test that HTTP 403 raises AuthError without retry."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="http://x", code=403, msg="Forbidden", hdrs={}, fp=None
            )

            from quota_sentinel.providers.errors import AuthError

            with pytest.raises(AuthError):
                http_post_json("https://example.com/api", {}, max_attempts=3)

            assert mock_urlopen.call_count == 1

    def test_retries_on_urlerror_network_error(self):
        """Test that URLError triggers retry."""
        import urllib.error

        with patch(
            "quota_sentinel.providers.http.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"key": "value"}'
            mock_cm = MagicMock()
            mock_cm.__enter__.return_value = mock_response
            mock_cm.__exit__.return_value = None

            mock_urlopen.side_effect = [
                urllib.error.URLError("Connection reset"),
                mock_cm,
            ]

            result = http_post_json(
                "https://example.com/api",
                {},
                max_attempts=3,
                base_delay=0.01,
            )

            assert result == {"key": "value"}
            assert mock_urlopen.call_count == 2
