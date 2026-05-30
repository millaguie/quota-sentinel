"""Base types and ABC for usage providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WindowUsage:
    """Usage data for a single rate-limit window."""

    utilization: float  # 0-100
    resets_at: datetime | None = None
    metadata: dict[str, Any] | None = None  # Provider-specific extra data


@dataclass
class UsageResult:
    """Normalized usage data from any provider."""

    provider: str
    windows: dict[str, WindowUsage] = field(default_factory=dict)
    error: str | None = None


class UsageProvider(ABC):
    """Base class for provider usage APIs.

    In quota-sentinel, providers receive tokens directly via constructor
    (no filesystem reading). The daemon is filesystem-agnostic.
    """

    name: str = "unknown"

    @abstractmethod
    def fetch(self) -> UsageResult:
        """Fetch current usage. Returns UsageResult (may have .error set)."""

    def merge_credentials_from(self, other: "UsageProvider") -> None:
        """Inherit credentials from ``other`` for fields that ``self`` left empty.

        Called by the store when two clients register against the same
        ``(provider_name, api_key)`` fingerprint.  The normal flow is "newer
        registration wins" — but a desktop client that auto-extracts cookies
        from a logged-out browser would otherwise overwrite a working cookie
        held by a programmatic client running on the same key.  This hook
        lets cookie-bearing providers (xiaomi, crofai, opencode_go, …) keep
        the existing credential when their own copy is missing.

        Default implementation: no-op.  Providers without a cookie/secret
        beyond ``api_key`` have nothing to merge — the fingerprint already
        encodes the only credential and the freshly-instantiated provider
        is functionally equivalent to the old one.
        """
        return None
