"""Server configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_HARD_CAPS: dict[str, float] = {
    "claude_five_hour": 80.0,
    "claude_seven_day": 90.0,
    "copilot_monthly": 85.0,
    "zai_default": 80.0,
    "minimax_default": 85.0,
    "deepseek_default": 85.0,
    "alibaba_default": 80.0,
}


@dataclass
class ServerConfig:
    """Quota-sentinel server configuration."""

    host: str = "127.0.0.1"
    port: int = 7878
    default_poll_interval: int = 300
    safety_margin_min: int = 30
    velocity_window: int = 10
    overcommit_factor: float = 1.5
    heartbeat_timeout_factor: float = 3.0
    hard_caps: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_HARD_CAPS))
