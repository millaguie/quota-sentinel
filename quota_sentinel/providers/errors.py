"""Provider error types and retry utilities."""

from __future__ import annotations

import logging
import time
import urllib.error
from dataclasses import dataclass
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F")


# ── Exception Hierarchy ────────────────────────────────────────────────────


class ProviderError(RuntimeError):
    """Base exception for provider-specific errors.

    All provider errors are RuntimeErrors (not checked exceptions) so they
    can propagate through the async daemon loop without declaration.
    """

    def __init__(self, message: str = "", provider: str = "unknown"):
        super().__init__(message)
        self.provider = provider


class AuthError(ProviderError):
    """Authentication or authorization failure (401, 403)."""

    def __init__(
        self, message: str = "authentication failed", provider: str = "unknown"
    ):
        super().__init__(message, provider)


class RateLimitError(ProviderError):
    """Rate limit hit (429). Caller should back off before retrying."""

    def __init__(self, message: str = "rate limited", provider: str = "unknown"):
        super().__init__(message, provider)


class TransientError(ProviderError):
    """Temporary failure that may succeed on retry (500-599, timeout)."""

    def __init__(self, message: str = "transient error", provider: str = "unknown"):
        super().__init__(message, provider)


class NetworkError(ProviderError):
    """Network-level failure (DNS, connection refused, timeout)."""

    def __init__(self, message: str = "network error", provider: str = "unknown"):
        super().__init__(message, provider)


# ── Retry Configuration ────────────────────────────────────────────────────


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    retry_on_timeout: bool = True  # retry on HTTP 599 (connection timeout)


# ── Error Classification ───────────────────────────────────────────────────


def classify_http_error(
    error: urllib.error.HTTPError, provider: str = "unknown"
) -> ProviderError:
    """Classify an HTTPError into a specific ProviderError type.

    Args:
        error: The HTTPError to classify
        provider: Provider name for context

    Returns:
        A ProviderError subclass appropriate for the HTTP status code
    """
    code = error.code
    reason = error.reason or f"HTTP {code}"

    # Auth failures - do not retry
    if code in (401, 403):
        return AuthError(message=f"{reason} (auth failed)", provider=provider)

    # Rate limit - do not retry (caller should back off)
    if code == 429:
        return RateLimitError(message=f"{reason} (rate limited)", provider=provider)

    # Gateway/server errors - retry
    if code in (500, 502, 503, 504):
        return TransientError(message=f"{reason} (server error)", provider=provider)

    # HTTP 599 is commonly used for connection timeouts
    if code == 599:
        return TransientError(message=f"{reason} (timeout)", provider=provider)

    # Treat all other errors as potentially transient
    return TransientError(message=f"{reason} (HTTP {code})", provider=provider)


def classify_network_error(
    error: urllib.error.URLError, provider: str = "unknown"
) -> NetworkError:
    """Classify a URLError into a NetworkError.

    Args:
        error: The URLError to classify
        provider: Provider name for context

    Returns:
        A NetworkError with the underlying reason
    """
    reason = str(error.reason) if error.reason else str(error)
    return NetworkError(message=f"network error: {reason}", provider=provider)


# ── Retry Decorator ───────────────────────────────────────────────────────


def retry_with_backoff(
    config: RetryConfig | None = None,
) -> Callable[[Callable[..., F]], Callable[..., F]]:
    """Decorator that retries a function on transient errors with exponential backoff.

    Args:
        config: Retry configuration. Uses sensible defaults if not provided.

    Returns:
        Decorated function that retries on transient failures.

    The decorated function is retried on:
    - HTTP 500-599 errors (server errors)
    - HTTP 599 (connection timeout)
    - urllib.error.URLError (network-level failures)

    It does NOT retry on:
    - AuthError (401, 403)
    - RateLimitError (429)
    - Other non-transient errors

    Example:
        @retry_with_backoff(RetryConfig(max_attempts=3, base_delay=1.0))
        def fetch_data():
            return http_get(url, headers)
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., F]) -> Callable[..., F]:
        def wrapper(*args, **kwargs) -> F:
            last_error: Exception | None = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except ProviderError:
                    # Re-raise provider-specific errors immediately
                    raise
                except urllib.error.HTTPError as e:
                    # Classify and potentially re-raise
                    classified = classify_http_error(e, provider="unknown")

                    # Don't retry auth or rate limit errors
                    if isinstance(classified, (AuthError, RateLimitError)):
                        raise classified from e

                    # Don't retry timeouts if configured to skip them
                    if e.code == 599 and not config.retry_on_timeout:
                        raise classified from e

                    # Retry on transient errors
                    last_error = classified
                    if attempt < config.max_attempts:
                        delay = min(
                            config.base_delay * (2 ** (attempt - 1)), config.max_delay
                        )
                        logger.debug(
                            "retry %s/%s in %.1fs after %s (%d)",
                            attempt,
                            config.max_attempts,
                            delay,
                            func.__name__,
                            e.code,
                        )
                        time.sleep(delay)
                    else:
                        raise classified from e

                except urllib.error.URLError as e:
                    # Network-level error - retry
                    last_error = classify_network_error(e, provider="unknown")
                    if attempt < config.max_attempts:
                        delay = min(
                            config.base_delay * (2 ** (attempt - 1)), config.max_delay
                        )
                        logger.debug(
                            "retry %s/%s in %.1fs after %s (URLError: %s)",
                            attempt,
                            config.max_attempts,
                            delay,
                            func.__name__,
                            e.reason,
                        )
                        time.sleep(delay)
                    else:
                        raise last_error from e

                except OSError as e:
                    # Other OS-level errors (connection refused, etc.)
                    last_error = NetworkError(
                        message=f"OS error: {e}", provider="unknown"
                    )
                    if attempt < config.max_attempts:
                        delay = min(
                            config.base_delay * (2 ** (attempt - 1)), config.max_delay
                        )
                        logger.debug(
                            "retry %s/%s in %.1fs after %s (OSError: %s)",
                            attempt,
                            config.max_attempts,
                            delay,
                            func.__name__,
                            e,
                        )
                        time.sleep(delay)
                    else:
                        raise last_error from e

            # Should not reach here, but safety net
            if last_error:
                raise last_error
            raise RuntimeError("retry_with_backoff: unexpected state")

        return wrapper

    return decorator
