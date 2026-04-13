"""Shared HTTP helpers for providers (stdlib only)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from quota_sentinel.providers.errors import (
    AuthError,
    NetworkError,
    RateLimitError,
    TransientError,
)

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Retry configuration for HTTP requests
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY = 1.0
_DEFAULT_MAX_DELAY = 60.0


def _classify_http_error(
    code: int, reason: str = ""
) -> AuthError | RateLimitError | TransientError:
    """Classify an HTTP status code into an appropriate error type.

    Args:
        code: HTTP status code
        reason: HTTP reason phrase

    Returns:
        Appropriate error type for the status code
    """
    reason = reason or f"HTTP {code}"
    if code in (401, 403):
        return AuthError(message=f"{reason} (auth failed)")
    if code == 429:
        return RateLimitError(message=f"{reason} (rate limited)")
    if code in (500, 502, 503, 504) or code == 599:
        return TransientError(message=f"{reason} (server error)")
    return TransientError(message=f"{reason} (HTTP {code})")


def http_get(
    url: str,
    headers: dict[str, str],
    timeout: int = 10,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay: float = _DEFAULT_BASE_DELAY,
    max_delay: float = _DEFAULT_MAX_DELAY,
) -> dict[str, Any]:
    """GET request returning parsed JSON with automatic retry on transient failures.

    Retries on:
    - HTTP 500-599 server errors
    - HTTP 599 (connection timeout)
    - Network errors (URLError, socket timeout)

    Does NOT retry on:
    - HTTP 401, 403 (auth failures)
    - HTTP 429 (rate limit - caller should back off)
    - Client errors other than above

    Args:
        url: The URL to fetch
        headers: HTTP headers to send
        timeout: Socket timeout in seconds
        max_attempts: Maximum number of retry attempts
        base_delay: Base delay between retries (exponential backoff)
        max_delay: Maximum delay between retries

    Returns:
        Parsed JSON response

    Raises:
        AuthError: For 401/403 responses
        RateLimitError: For 429 responses
        TransientError: After max attempts exhausted for transient errors
        NetworkError: For network-level failures
    """
    hdrs = {"User-Agent": _UA}
    hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method="GET")

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            classified = _classify_http_error(e.code, e.reason or "")
            # Don't retry auth or rate limit errors
            if isinstance(classified, (AuthError, RateLimitError)):
                raise classified from e
            # Retry on transient errors
            last_error = classified
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.debug(
                    "http_get retry %s/%s in %.1fs (HTTP %d %s)",
                    attempt,
                    max_attempts,
                    delay,
                    e.code,
                    e.reason,
                )
                time.sleep(delay)
            else:
                raise classified from e
        except urllib.error.URLError as e:
            last_error = NetworkError(message=f"network error: {e.reason}")
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.debug(
                    "http_get retry %s/%s in %.1fs (URLError: %s)",
                    attempt,
                    max_attempts,
                    delay,
                    e.reason,
                )
                time.sleep(delay)
            else:
                raise last_error from e
        except TimeoutError as e:
            last_error = TransientError(message=f"timeout ({e})")
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.debug(
                    "http_get retry %s/%s in %.1fs (TimeoutError)",
                    attempt,
                    max_attempts,
                    delay,
                )
                time.sleep(delay)
            else:
                raise last_error from e
        except OSError as e:
            last_error = NetworkError(message=f"OS error: {e}")
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.debug(
                    "http_get retry %s/%s in %.1fs (OSError: %s)",
                    attempt,
                    max_attempts,
                    delay,
                    e,
                )
                time.sleep(delay)
            else:
                raise last_error from e

    # Should not reach here
    if last_error:
        raise last_error
    raise RuntimeError("http_get: unexpected state")


def http_post_json(
    url: str,
    body: dict,
    headers: dict[str, str] | None = None,
    timeout: int = 10,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay: float = _DEFAULT_BASE_DELAY,
    max_delay: float = _DEFAULT_MAX_DELAY,
) -> dict[str, Any]:
    """POST JSON body, return parsed JSON response with automatic retry.

    Retries on:
    - HTTP 500-599 server errors
    - HTTP 599 (connection timeout)
    - Network errors (URLError, socket timeout)

    Does NOT retry on:
    - HTTP 401, 403 (auth failures)
    - HTTP 429 (rate limit - caller should back off)
    - Client errors other than above

    Args:
        url: The URL to POST to
        body: JSON-serializable body
        headers: Additional HTTP headers
        timeout: Socket timeout in seconds
        max_attempts: Maximum number of retry attempts
        base_delay: Base delay between retries (exponential backoff)
        max_delay: Maximum delay between retries

    Returns:
        Parsed JSON response

    Raises:
        AuthError: For 401/403 responses
        RateLimitError: For 429 responses
        TransientError: After max attempts exhausted for transient errors
        NetworkError: For network-level failures
    """
    data = json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json", "User-Agent": _UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            classified = _classify_http_error(e.code, e.reason or "")
            # Don't retry auth or rate limit errors
            if isinstance(classified, (AuthError, RateLimitError)):
                raise classified from e
            # Retry on transient errors
            last_error = classified
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.debug(
                    "http_post_json retry %s/%s in %.1fs (HTTP %d %s)",
                    attempt,
                    max_attempts,
                    delay,
                    e.code,
                    e.reason,
                )
                time.sleep(delay)
            else:
                raise classified from e
        except urllib.error.URLError as e:
            last_error = NetworkError(message=f"network error: {e.reason}")
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.debug(
                    "http_post_json retry %s/%s in %.1fs (URLError: %s)",
                    attempt,
                    max_attempts,
                    delay,
                    e.reason,
                )
                time.sleep(delay)
            else:
                raise last_error from e
        except TimeoutError as e:
            last_error = TransientError(message=f"timeout ({e})")
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.debug(
                    "http_post_json retry %s/%s in %.1fs (TimeoutError)",
                    attempt,
                    max_attempts,
                    delay,
                )
                time.sleep(delay)
            else:
                raise last_error from e
        except OSError as e:
            last_error = NetworkError(message=f"OS error: {e}")
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                logger.debug(
                    "http_post_json retry %s/%s in %.1fs (OSError: %s)",
                    attempt,
                    max_attempts,
                    delay,
                    e,
                )
                time.sleep(delay)
            else:
                raise last_error from e

    # Should not reach here
    if last_error:
        raise last_error
    raise RuntimeError("http_post_json: unexpected state")
