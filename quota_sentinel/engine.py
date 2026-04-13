"""Velocity tracking and status evaluation engine."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from quota_sentinel.providers.base import UsageResult

if TYPE_CHECKING:
    from quota_sentinel.calibration import TokenCalibrator
    from quota_sentinel.opencode_db import SessionStats


@dataclass
class _Sample:
    timestamp: float  # time.time()
    utilization: float  # 0-100


class VelocityTracker:
    """Tracks utilization samples and computes velocity (%/hour)."""

    def __init__(self, max_samples: int = 10):
        self._samples: deque[_Sample] = deque(maxlen=max_samples)

    def add(self, utilization: float) -> None:
        self._samples.append(_Sample(timestamp=time.time(), utilization=utilization))

    def velocity_pct_per_hour(self) -> float:
        """Linear slope of utilization over time, in %/hour.

        Returns 0 if insufficient data (< 2 samples).
        Negative velocity (usage going down) is clamped to 0.
        """
        if len(self._samples) < 2:
            return 0.0

        n = len(self._samples)
        t_mean = sum(s.timestamp for s in self._samples) / n
        u_mean = sum(s.utilization for s in self._samples) / n

        num = sum(
            (s.timestamp - t_mean) * (s.utilization - u_mean) for s in self._samples
        )
        den = sum((s.timestamp - t_mean) ** 2 for s in self._samples)

        if den == 0:
            return 0.0

        slope_per_sec = num / den
        slope_per_hour = slope_per_sec * 3600
        return max(slope_per_hour, 0.0)

    def projected_exhaustion_min(self, current: float, cap: float) -> float | None:
        """Minutes until utilization reaches cap at current velocity."""
        if current >= cap:
            return 0.0
        v = self.velocity_pct_per_hour()
        if v <= 0:
            return None
        remaining_pct = cap - current
        hours = remaining_pct / v
        return hours * 60


def get_hard_cap(provider: str, window: str, caps: dict[str, float]) -> float:
    """Look up the hard cap for a provider/window combination."""
    specific = f"{provider}_{window}"
    provider_default = f"{provider}_default"
    return caps.get(specific, caps.get(provider_default, 85.0))


def compute_avg_tokens_per_session(session_stats: list[SessionStats]) -> float | None:
    """Compute average tokens per session from session statistics.

    Returns None if no sessions available.
    """
    if not session_stats:
        return None
    total_tokens = sum(s.total_tokens for s in session_stats)
    count = len(session_stats)
    if count == 0:
        return None
    return total_tokens / count


def estimated_sessions_remaining(
    calibrator: TokenCalibrator,
    session_stats: list[SessionStats],
    provider: str,
    window: str,
    utilization: float,
    hard_cap: float,
) -> float | None:
    """Estimate remaining sessions based on calibrated tokens and average session size.

    Returns None if calibration or session stats are unavailable.
    """
    # Get calibrated tokens for current utilization
    current_tokens = calibrator.utilization_to_tokens(provider, window, utilization)
    if current_tokens is None:
        return None

    # Get calibrated tokens at hard cap (total capacity)
    cap_tokens = calibrator.utilization_to_tokens(provider, window, hard_cap)
    if cap_tokens is None:
        return None

    # Remaining tokens
    remaining_tokens = max(0, cap_tokens - current_tokens)

    # Average tokens per session
    avg_tokens = compute_avg_tokens_per_session(session_stats)
    if avg_tokens is None or avg_tokens <= 0:
        return None

    return remaining_tokens / avg_tokens


def _window_status(
    utilization: float,
    velocity: float,
    hard_cap: float,
    safety_margin_min: float,
) -> str:
    """Determine GREEN/YELLOW/RED for a single window."""
    if utilization >= hard_cap:
        return "RED"

    velocity_buffer = velocity * (safety_margin_min / 60)
    dynamic_threshold = hard_cap - velocity_buffer

    if utilization >= dynamic_threshold:
        if velocity > 0:
            remaining_pct = hard_cap - utilization
            minutes_left = (remaining_pct / velocity) * 60
            if minutes_left <= safety_margin_min:
                return "RED"
        return "YELLOW"

    return "GREEN"


def evaluate(
    results: dict[str, UsageResult],
    velocities: dict[str, dict[str, VelocityTracker]],
    hard_caps: dict[str, float],
    safety_margin_min: int = 30,
    framework: str = "opencode",
    calibrator: TokenCalibrator | None = None,
    session_stats: list[SessionStats] | None = None,
    sessions_remaining_threshold: float = 1.5,
) -> dict[str, Any]:
    """Evaluate all provider results and produce a TOKEN_STATUS dict."""

    from datetime import UTC, datetime

    # Import SessionStats type for type checking
    if session_stats is None:
        session_stats = []

    provider_statuses: dict[str, Any] = {}
    worst_status = "GREEN"
    status_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    messages: list[str] = []

    for prov_name, result in results.items():
        if result.error:
            provider_statuses[prov_name] = {
                "status": "UNKNOWN",
                "error": result.error,
            }
            continue

        prov_worst = "GREEN"
        windows_out: dict[str, Any] = {}

        for wname, wdata in result.windows.items():
            tracker = velocities.get(prov_name, {}).get(wname)
            vel = tracker.velocity_pct_per_hour() if tracker else 0.0
            cap = get_hard_cap(prov_name, wname, hard_caps)

            w_status = _window_status(wdata.utilization, vel, cap, safety_margin_min)

            exhaust_min = None
            if tracker:
                exhaust_min = tracker.projected_exhaustion_min(wdata.utilization, cap)

            # Compute sessions remaining if calibration data is available
            sessions_remaining: float | None = None
            if calibrator is not None:
                sessions_remaining = estimated_sessions_remaining(
                    calibrator,
                    session_stats,
                    prov_name,
                    wname,
                    wdata.utilization,
                    cap,
                )
                # Factor low sessions_remaining into status
                if (
                    sessions_remaining is not None
                    and sessions_remaining < sessions_remaining_threshold
                ):
                    # If sessions remaining is critically low, escalate status
                    if sessions_remaining < sessions_remaining_threshold / 2:
                        w_status = "RED"
                    else:
                        # Use worse of current status or YELLOW
                        if status_order.get(w_status, 0) < status_order.get(
                            "YELLOW", 0
                        ):
                            w_status = "YELLOW"

            windows_out[wname] = {
                "utilization": round(wdata.utilization, 1),
                "velocity_pct_per_hour": round(vel, 1),
                "projected_exhaustion_min": round(exhaust_min)
                if exhaust_min is not None
                else None,
                "resets_at": wdata.resets_at.isoformat() if wdata.resets_at else None,
                "status": w_status,
                "sessions_remaining": round(sessions_remaining, 1)
                if sessions_remaining is not None
                else None,
            }

            if status_order.get(w_status, 0) > status_order.get(prov_worst, 0):
                prov_worst = w_status

            if w_status in ("YELLOW", "RED"):
                time_str = (
                    f"~{round(exhaust_min)}min left"
                    if exhaust_min is not None
                    else "growing"
                )
                sessions_str = (
                    f", {sessions_remaining:.1f} sessions left"
                    if sessions_remaining is not None
                    else ""
                )
                messages.append(
                    f"{prov_name} {wname} at {wdata.utilization:.0f}% ({time_str}{sessions_str})"
                )

        provider_statuses[prov_name] = {"status": prov_worst, "windows": windows_out}

        if status_order.get(prov_worst, 0) > status_order.get(worst_status, 0):
            worst_status = prov_worst

    # Recommendation
    active_providers = [p for p, r in results.items() if not r.error]
    red_providers = [
        p
        for p in active_providers
        if provider_statuses.get(p, {}).get("status") == "RED"
    ]
    green_providers = [
        p
        for p in active_providers
        if provider_statuses.get(p, {}).get("status") == "GREEN"
    ]
    all_exhausted = (
        len(red_providers) == len(active_providers) and len(active_providers) > 0
    )

    if framework == "claude":
        if worst_status == "RED":
            recommendation = "STOP"
        elif worst_status == "YELLOW":
            recommendation = "PROCEED_SMALL_ONLY"
        else:
            recommendation = "PROCEED"
    else:
        if all_exhausted:
            recommendation = "STOP"
        elif worst_status == "RED" and green_providers:
            recommendation = "PROCEED"
            messages.append(
                f"OpenCode will auto-retry with: {', '.join(green_providers)}"
            )
        elif worst_status == "YELLOW":
            recommendation = "PROCEED_SMALL_ONLY"
        else:
            recommendation = "PROCEED"

    message = "; ".join(messages) if messages else "All providers healthy"

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "framework": framework,
        "overall_status": worst_status,
        "recommendation": recommendation,
        "message": message,
        "providers": provider_statuses,
        "alternative_providers": sorted(green_providers),
        "all_exhausted": all_exhausted,
    }
