"""Alibaba Cloud (Tongyi Lingma) coding plan usage provider."""

from __future__ import annotations

import urllib.error
from datetime import UTC, datetime
from typing import Any

from quota_sentinel.providers.base import UsageProvider, UsageResult, WindowUsage
from quota_sentinel.providers.http import http_post_json

_ALIBABA_REGIONS = {
    "intl": {
        "host": "https://modelstudio.console.alibabacloud.com",
        "region_id": "ap-southeast-1",
        "commodity_code": "sfm_codingplan_public_intl",
    },
    "cn": {
        "host": "https://bailian.console.aliyun.com",
        "region_id": "cn-beijing",
        "commodity_code": "sfm_codingplan_public_cn",
    },
}


class AlibabaUsageProvider(UsageProvider):
    """Alibaba Cloud coding plan — 5h/weekly/monthly quotas.

    Uses undocumented console RPC endpoint.
    """

    name = "alibaba"

    def __init__(self, api_token: str, region: str = "intl"):
        self.api_token = api_token
        self.region = region

    def fetch(self) -> UsageResult:
        if not self.api_token:
            return UsageResult(provider=self.name, error="no token")

        rcfg = _ALIBABA_REGIONS.get(self.region, _ALIBABA_REGIONS["intl"])
        url = (
            f"{rcfg['host']}/data/api.json"
            f"?action=zeldaEasy.broadscope-bailian.codingPlan"
            f".queryCodingPlanInstanceInfoV2"
            f"&product=broadscope-bailian"
            f"&api=queryCodingPlanInstanceInfoV2"
            f"&currentRegionId={rcfg['region_id']}"
        )
        body = {
            "queryCodingPlanInstanceInfoRequest": {
                "commodityCode": rcfg["commodity_code"],
            },
        }
        try:
            data = http_post_json(
                url,
                body,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "x-api-key": self.api_token,
                    "X-DashScope-API-Key": self.api_token,
                },
            )
        except urllib.error.HTTPError as e:
            error_map = {401: "auth failed", 429: "rate limited"}
            return UsageResult(
                provider=self.name, error=error_map.get(e.code, f"HTTP {e.code}")
            )
        except Exception as e:
            return UsageResult(provider=self.name, error=str(e))

        if data.get("code") == "ConsoleNeedLogin":
            return UsageResult(provider=self.name, error="ConsoleNeedLogin")

        quota_info = self._find_quota(data)
        if not quota_info:
            return UsageResult(provider=self.name, error="no quota data")

        windows: dict[str, WindowUsage] = {}
        for label, prefix in [
            ("5h", "per5Hour"),
            ("weekly", "perWeek"),
            ("monthly", "perBillMonth"),
        ]:
            used = quota_info.get(f"{prefix}UsedQuota")
            total = quota_info.get(f"{prefix}TotalQuota")
            if total is not None and used is not None and int(total) > 0:
                pct = int(used) / int(total) * 100
                ra = None
                rt = quota_info.get(f"{prefix}QuotaNextRefreshTime")
                if rt:
                    ra = self._parse_reset(rt)
                windows[label] = WindowUsage(min(pct, 100), ra)

        return UsageResult(provider=self.name, windows=windows)

    @staticmethod
    def _parse_reset(value: Any) -> datetime | None:
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value / 1000, tz=UTC)
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    def _find_quota(data: dict) -> dict | None:
        """Navigate nested response to find codingPlanQuotaInfo."""
        for root in [
            data,
            data.get("data", {}),
            data.get("data", {}).get("result", {}),
            data.get("result", {}),
        ]:
            if not isinstance(root, dict):
                continue
            instances = root.get("codingPlanInstanceInfos")
            if isinstance(instances, list) and instances:
                inst = instances[0]
                return inst.get("codingPlanQuotaInfo", inst)
        return AlibabaUsageProvider._search_quota(data, depth=0)

    @staticmethod
    def _search_quota(obj: Any, depth: int) -> dict | None:
        if depth > 5 or not isinstance(obj, dict):
            return None
        if "per5HourTotalQuota" in obj:
            return obj
        for v in obj.values():
            if isinstance(v, dict):
                result = AlibabaUsageProvider._search_quota(v, depth + 1)
                if result:
                    return result
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        result = AlibabaUsageProvider._search_quota(item, depth + 1)
                        if result:
                            return result
        return None
