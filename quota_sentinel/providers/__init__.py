"""Provider factory and auth-key mapping."""

from __future__ import annotations

from typing import Any

from quota_sentinel.providers.alibaba import AlibabaUsageProvider
from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.claude import ClaudeUsageProvider
from quota_sentinel.providers.copilot import CopilotUsageProvider
from quota_sentinel.providers.deepseek import DeepSeekUsageProvider
from quota_sentinel.providers.minimax import MiniMaxUsageProvider
from quota_sentinel.providers.zai import ZaiUsageProvider

__all__ = [
    "UsageProvider",
    "UsageResult",
    "WindowUsage",
    "create_provider",
    "AUTH_KEY_TO_PROVIDER",
]

# Maps opencode auth.json key names → provider names
AUTH_KEY_TO_PROVIDER: dict[str, str] = {
    "zai-coding-plan": "zai",
    "zai": "zai",
    "github-copilot": "copilot",
    "minimax-coding-plan": "minimax",
    "minimax": "minimax",
    "deepseek-coding-plan": "deepseek",
    "deepseek": "deepseek",
    "bailian-coding-plan": "alibaba",
    "alibaba-coding-plan": "alibaba",
    "dashscope": "alibaba",
    "alibaba": "alibaba",
}


def create_provider(name: str, config: dict[str, Any]) -> UsageProvider:
    """Create a usage provider from a name and config dict.

    Config keys vary per provider — see each provider's __init__ for details.
    All providers accept their API token directly (no filesystem reading).
    """
    if name == "claude":
        return ClaudeUsageProvider(
            access_token=config.get("access_token", ""),
            refresh_token=config.get("refresh_token", ""),
            expires_at=config.get("expires_at", 0),
        )
    if name == "copilot":
        return CopilotUsageProvider(
            github_username=config.get("github_username", ""),
            github_token=config.get("github_token", ""),
            plan=config.get("plan", "pro"),
        )
    if name == "zai":
        return ZaiUsageProvider(api_token=config["key"])
    if name == "minimax":
        return MiniMaxUsageProvider(
            api_token=config["key"],
            group_id=config.get("group_id", ""),
        )
    if name == "deepseek":
        return DeepSeekUsageProvider(
            api_token=config["key"],
            reference_balance=config.get("reference_balance"),
        )
    if name == "alibaba":
        return AlibabaUsageProvider(
            api_token=config["key"],
            region=config.get("region", "intl"),
        )
    raise ValueError(f"Unknown provider: {name}")
