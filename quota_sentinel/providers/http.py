"""Shared HTTP helpers for providers (stdlib only)."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def http_get(url: str, headers: dict[str, str], timeout: int = 10) -> dict[str, Any]:
    """GET request returning parsed JSON. Raises on error."""
    hdrs = {"User-Agent": _UA}
    hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_post_json(
    url: str,
    body: dict,
    headers: dict[str, str] | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    """POST JSON body, return parsed JSON response."""
    data = json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json", "User-Agent": _UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())
