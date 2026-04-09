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
