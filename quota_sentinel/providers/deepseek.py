"""DeepSeek balance usage provider."""

from __future__ import annotations

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.errors import AuthError, RateLimitError, TransientError
from quota_sentinel.providers.http import http_get

DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"


class DeepSeekUsageProvider(UsageProvider):
    """DeepSeek — balance-based (not percentage).

    Converts balance to pseudo-utilization: 100 - (balance / ref * 100).
    ref defaults to the first observed balance (or 10 if unknown).
    """

    name = "deepseek"

    def __init__(self, api_token: str, reference_balance: float | None = None):
        self.api_token = api_token
        self._ref_balance = reference_balance

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")

        try:
            data = http_get(
                DEEPSEEK_BALANCE_URL,
                headers={"Authorization": f"Bearer {self.api_token}"},
            )
        except AuthError as e:
            return UsageResult(provider=self.name, error=str(e))
        except RateLimitError as e:
            return UsageResult(provider=self.name, error=str(e))
        except TransientError as e:
            return UsageResult(provider=self.name, error=str(e))
        except Exception as e:
            return UsageResult(provider=self.name, error=f"unexpected error: {e}")

        balances = data.get("balance_infos", [])
        if not balances:
            return UsageResult(provider=self.name, error="no balance data")

        bal = balances[0]
        total = float(bal.get("total_balance", "0"))
        is_available = data.get("is_available", total > 0)

        if self._ref_balance is None:
            self._ref_balance = total if total > 0 else 1.0
        ref = self._ref_balance

        pct = max(0.0, 100.0 - (total / ref * 100)) if ref > 0 else 0.0
        if not is_available:
            pct = 100.0

        return UsageResult(
            provider=self.name,
            windows={
                "balance": WindowUsage(
                    utilization=min(pct, 100.0),
                    resets_at=None,
                    metadata={
                        "total_balance": total,
                        "is_available": is_available,
                        "currency": bal.get("currency", "USD"),
                    },
                )
            },
        )
