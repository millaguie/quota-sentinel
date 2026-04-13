"""Server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from quota_sentinel.opencode_db import OpenCodeDBConfig

DEFAULT_HARD_CAPS: dict[str, float] = {
    "claude_five_hour": 80.0,
    "claude_seven_day": 90.0,
    "copilot_monthly": 85.0,
    "zai_default": 80.0,
    "minimax_default": 85.0,
    "deepseek_default": 85.0,
    "alibaba_default": 80.0,
    "cerebras_default": 85.0,
    "openai_default": 85.0,
    "opencode_default": 80.0,
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
    enable_opencode_db: bool = False
    opencode_db_path: Path | None = None
    opencode_poll_interval: int = 60
    opencode_db: OpenCodeDBConfig | None = field(default=None, init=False)
    sessions_remaining_threshold: float = 1.5

    def __post_init__(self) -> None:
        """Build opencode_db config from enable_opencode_db and opencode_db_path."""
        if self.enable_opencode_db and self.opencode_db_path:
            self.opencode_db = OpenCodeDBConfig(db_path=self.opencode_db_path)
        elif self.enable_opencode_db:
            self.opencode_db = OpenCodeDBConfig()
        else:
            self.opencode_db = None

    @classmethod
    def from_env(cls) -> ServerConfig:
        """Create ServerConfig from environment variables.

        Environment variables override defaults but not explicit constructor args.

        Supported env vars:
            HOST: Bind address (default: 127.0.0.1)
            PORT: Bind port (default: 7878)
            POLL_INTERVAL: Default poll interval in seconds (default: 300)
        """
        return cls(
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "7878")),
            default_poll_interval=int(os.environ.get("POLL_INTERVAL", "300")),
        )
