"""Token-per-percentage calibration for quota-sentinel.

Calibrates how many tokens = 1% of each provider/window quota by cross-referencing
provider utilization% deltas with tokens consumed from OpenCode DB.

Usage:
    calibrator = TokenCalibrator(window=5)
    calibrator.record("claude", "hourly", tokens_delta=1500, utilization_delta_pct=10.0)
    tokens_per_pct = calibrator.tokens_per_pct("claude", "hourly")  # e.g., 150.0
    absolute_tokens = calibrator.utilization_to_tokens("claude", "hourly", 50.0)  # 7500
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CalibrationEntry:
    """A single calibration measurement."""

    timestamp: float  # time.time() when entry was recorded
    tokens_delta: int  # tokens consumed between polls
    utilization_delta_pct: float  # utilization% change between polls
    tokens_per_pct: float  # derived: tokens_delta / utilization_delta_pct

    @property
    def age_seconds(self) -> float:
        return time.time() - self.timestamp


@dataclass
class CalibrationWindowData:
    """Stores calibration entries and computes moving average for a provider/window."""

    entries: deque[CalibrationEntry] = field(default_factory=lambda: deque(maxlen=20))

    def add_entry(self, entry: CalibrationEntry) -> None:
        self.entries.append(entry)

    def tokens_per_pct(self, min_entries: int = 2) -> float | None:
        """Return moving average of tokens_per_pct across entries.

        Returns None if fewer than min_entries valid entries exist.
        Only considers entries with positive utilization_delta_pct.
        """
        valid = [e.tokens_per_pct for e in self.entries if e.utilization_delta_pct > 0]
        if len(valid) < min_entries:
            return None
        return sum(valid) / len(valid)

    def clear(self) -> None:
        self.entries.clear()


class TokenCalibrator:
    """Tracks calibration data per provider/window with moving average smoothing.

    Calibration is computed by cross-referencing:
      (a) utilization% delta from provider API between two polls
      (b) tokens consumed from OpenCode DB for the same period

    The ratio tokens_delta / utilization_delta_pct gives tokens per 1% for that window.
    """

    DEFAULT_WINDOW: int = 5  # moving average over last 5 calibrations

    def __init__(self, window_size: int | None = None):
        self.window_size = window_size or self.DEFAULT_WINDOW
        # Storage: {(provider, window): CalibrationWindowData}
        self._data: dict[tuple[str, str], CalibrationWindowData] = {}

    def _key(self, provider: str, window: str) -> tuple[str, str]:
        return (provider, window)

    def _get_or_create(self, provider: str, window: str) -> CalibrationWindowData:
        key = self._key(provider, window)
        if key not in self._data:
            self._data[key] = CalibrationWindowData()
        return self._data[key]

    def record(
        self,
        provider: str,
        window: str,
        tokens_delta: int,
        utilization_delta_pct: float,
    ) -> CalibrationEntry | None:
        """Record a new calibration measurement.

        Args:
            provider: Provider name (e.g., "claude", "deepseek")
            window: Window name (e.g., "hourly", "daily")
            tokens_delta: Number of tokens consumed between the two polls
            utilization_delta_pct: Change in utilization% over the same period

        Returns:
            CalibrationEntry if recorded successfully, None if skipped (e.g., zero delta)
        """
        if utilization_delta_pct <= 0:
            logger.debug(
                "Skipping calibration for %s/%s: utilization_delta_pct=%.2f <= 0",
                provider,
                window,
                utilization_delta_pct,
            )
            return None

        if tokens_delta < 0:
            logger.warning(
                "Skipping calibration for %s/%s: tokens_delta=%d < 0",
                provider,
                window,
                tokens_delta,
            )
            return None

        tokens_per_pct = tokens_delta / utilization_delta_pct
        entry = CalibrationEntry(
            timestamp=time.time(),
            tokens_delta=tokens_delta,
            utilization_delta_pct=utilization_delta_pct,
            tokens_per_pct=tokens_per_pct,
        )

        cal_data = self._get_or_create(provider, window)
        cal_data.add_entry(entry)

        logger.info(
            "Calibration recorded: %s/%s -> %.1f tokens/%% (avg: %s, n=%d)",
            provider,
            window,
            tokens_per_pct,
            cal_data.tokens_per_pct(min_entries=1),
            len(cal_data.entries),
        )

        return entry

    def tokens_per_pct(
        self,
        provider: str,
        window: str,
        min_entries: int | None = None,
    ) -> float | None:
        """Get moving average of tokens per percentage point.

        Args:
            provider: Provider name
            window: Window name
            min_entries: Minimum entries required (default: window_size)

        Returns:
            Average tokens per 1% utilization, or None if insufficient data
        """
        key = self._key(provider, window)
        cal_data = self._data.get(key)
        if not cal_data:
            return None
        return cal_data.tokens_per_pct(min_entries=min_entries or self.window_size)

    def utilization_to_tokens(
        self,
        provider: str,
        window: str,
        utilization_pct: float,
    ) -> int | None:
        """Convert utilization% to absolute token count using calibrated ratio.

        Args:
            provider: Provider name
            window: Window name
            utilization_pct: Current utilization percentage

        Returns:
            Estimated absolute token count, or None if calibration unavailable
        """
        ratio = self.tokens_per_pct(provider, window, min_entries=1)
        if ratio is None:
            return None
        return int(utilization_pct * ratio)

    def clear(self, provider: str | None = None, window: str | None = None) -> None:
        """Clear calibration data.

        Args:
            provider: If provided, only clear for this provider
            window: If provided, only clear for this window (requires provider)
        """
        if provider is None:
            self._data.clear()
            return

        if window is None:
            # Clear all windows for this provider
            for key in list(self._data.keys()):
                if key[0] == provider:
                    del self._data[key]
        else:
            key = self._key(provider, window)
            self._data.pop(key, None)

    def calibration_snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all calibration data for API responses."""
        from datetime import UTC, datetime

        result: dict[str, Any] = {}
        for (provider, window), cal_data in self._data.items():
            avg = cal_data.tokens_per_pct(min_entries=1)
            if avg is None:
                continue
            entries_out = [
                {
                    "tokens_delta": e.tokens_delta,
                    "utilization_delta_pct": round(e.utilization_delta_pct, 2),
                    "tokens_per_pct": round(e.tokens_per_pct, 1),
                    "age_seconds": round(e.age_seconds, 1),
                }
                for e in cal_data.entries
            ]
            result[f"{provider}:{window}"] = {
                "tokens_per_pct": round(avg, 1),
                "sample_count": len(cal_data.entries),
                "entries": entries_out,
            }
        return result
