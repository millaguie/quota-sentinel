#!/usr/bin/env python3
"""Estimate what CrofAI usage *would have cost* under pay-as-you-go pricing.

Background
----------
On 2026-05-31 (17:00 CDT) crof.ai retired its subscription plans and moved to
a purely pay-as-you-go, per-token model (https://crof.ai/blog/pricing-changes).
This script answers: "if every token I burned under the subscription had been
billed at the new per-token API prices, what would the bill have been?"

It cross-references two crof.ai endpoints:

* ``/user-api/usage``  — cumulative lifetime ``input_tokens`` / ``output_tokens``
  per model (requires the Flask ``session`` cookie from a browser login).
* ``/v1/models``       — per-model pay-as-you-go pricing in $/M tokens
  (``prompt`` = input, ``completion`` = output, ``cache_prompt`` = cached
  input). Public endpoint; an API key is optional.

Cost per model = input_tokens/1e6 * prompt + output_tokens/1e6 * completion

Caveats
-------
* ``/user-api/usage`` reports **cumulative, lifetime** totals — not a billing
  period. The figure is "total cost of all usage ever", not a monthly bill.
* The usage endpoint does not break out cache hits, so every input token is
  charged at the full (uncached) ``prompt`` rate. Real pay-as-you-go cost would
  be *lower* where prompt-cache discounts applied — treat the total as an
  upper bound on input cost.
* Models present in usage but absent from ``/v1/models`` (retired/renamed) have
  no price and are listed separately, excluded from the total.

Credentials
-----------
Session cookie (for usage), resolved in order:
  1. ``--cookie VALUE``
  2. ``$CROF_SESSION``
  3. browser cookie store (``--browser``, default ``chrome``), via the
     streamdeck-linux-gui ``browser_cookies`` helper if importable.
API key (optional, only for authenticated ``/v1/models``):
  ``--api-key`` or ``$CROF_API_KEY``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

USAGE_URL = "https://crof.ai/user-api/usage"
MODELS_URL = "https://crof.ai/v1/models"

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Default location of the streamdeck-linux-gui browser-cookie helper, used to
# auto-extract the crof.ai ``session`` cookie from the local browser store.
_BROWSER_COOKIES_PATH = (
    Path.home()
    / "workspace"
    / "streamdeck-linux-gui"
    / "streamdeck_ui"
    / "plugin_system"
    / "browser_cookies.py"
)


def _resolve_cookie(args: argparse.Namespace) -> str:
    """Resolve the crof.ai ``session`` cookie from arg, env, or browser store."""
    if args.cookie:
        return args.cookie.strip()
    env = os.environ.get("CROF_SESSION", "").strip()
    if env:
        return env
    helper = Path(args.browser_cookies or _BROWSER_COOKIES_PATH)
    if not helper.is_file():
        return ""
    try:
        spec = importlib.util.spec_from_file_location("browser_cookies", helper)
        assert spec and spec.loader
        bc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bc)
        cookies = bc.list_cookies("crof.ai", browser=args.browser)
        return (cookies.get("session") or "").strip()
    except Exception as e:  # noqa: BLE001
        print(f"warning: browser cookie extraction failed: {e}", file=sys.stderr)
        return ""


def _get_json(url: str, *, cookie: str = "", api_key: str = "", timeout: int = 20):
    headers = {"Accept": "application/json, text/plain, */*", "User-Agent": _BROWSER_UA}
    if cookie:
        headers["Cookie"] = f"session={cookie}"
        headers["Referer"] = "https://crof.ai/dashboard"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode(errors="replace"))


def _build_price_map(models_payload) -> dict[str, dict[str, str]]:
    models = (
        models_payload.get("data", models_payload)
        if isinstance(models_payload, dict)
        else models_payload
    )
    return {
        m["id"]: m.get("pricing", {})
        for m in models
        if isinstance(m, dict) and m.get("id")
    }


def compute_report(usage: dict, prices: dict[str, dict[str, str]]) -> dict:
    """Return a structured cost report from usage + pricing maps."""
    rows: list[dict] = []
    unmatched: list[dict] = []
    total = 0.0
    for mid, u in usage.items():
        if not isinstance(u, dict):
            continue
        it = int(u.get("input_tokens", 0) or 0)
        ot = int(u.get("output_tokens", 0) or 0)
        p = prices.get(mid)
        if not p:
            unmatched.append({"model": mid, "input_tokens": it, "output_tokens": ot})
            continue
        cost_in = it / 1e6 * float(p.get("prompt", 0) or 0)
        cost_out = ot / 1e6 * float(p.get("completion", 0) or 0)
        cost = cost_in + cost_out
        total += cost
        rows.append(
            {
                "model": mid,
                "input_tokens": it,
                "output_tokens": ot,
                "prompt_price": float(p.get("prompt", 0) or 0),
                "completion_price": float(p.get("completion", 0) or 0),
                "cost_input": round(cost_in, 4),
                "cost_output": round(cost_out, 4),
                "cost_total": round(cost, 4),
            }
        )
    rows.sort(key=lambda r: r["cost_total"], reverse=True)
    return {"rows": rows, "unmatched": unmatched, "total_cost": round(total, 2)}


def _print_table(report: dict) -> None:
    rows = report["rows"]
    print(
        f"{'model':28}{'in_tok':>16}{'out_tok':>14}"
        f"{'$in':>10}{'$out':>10}{'$total':>11}"
    )
    print("-" * 89)
    for r in rows:
        print(
            f"{r['model']:28}{r['input_tokens']:>16,}{r['output_tokens']:>14,}"
            f"{r['cost_input']:>10.2f}{r['cost_output']:>10.2f}{r['cost_total']:>11.2f}"
        )
    print("-" * 89)
    print(
        f"{'TOTAL (pay-as-you-go)':28}{'':>16}{'':>14}{'':>10}{'':>10}"
        f"{report['total_cost']:>11.2f}"
    )
    if report["unmatched"]:
        print("\nUnmatched models (no pay-as-you-go price in /v1/models, excluded):")
        for u in report["unmatched"]:
            print(
                f"  {u['model']:26} in={u['input_tokens']:,} out={u['output_tokens']:,}"
            )
    print(
        "\nNote: totals are cumulative LIFETIME usage; input is charged at the full "
        "(uncached) rate,\nso the figure is an upper bound on input cost.",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--cookie", help="crof.ai session cookie value (overrides env/browser)"
    )
    ap.add_argument(
        "--api-key",
        default=os.environ.get("CROF_API_KEY", ""),
        help="crof.ai API key (optional; /v1/models is public)",
    )
    ap.add_argument(
        "--browser",
        default="chrome",
        help="browser to extract the session cookie from (default: chrome)",
    )
    ap.add_argument(
        "--browser-cookies", help="path to streamdeck browser_cookies.py helper"
    )
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)

    cookie = _resolve_cookie(args)
    if not cookie:
        print(
            "error: no crof.ai session cookie. Pass --cookie, set $CROF_SESSION, "
            "or ensure the browser_cookies helper can read it.",
            file=sys.stderr,
        )
        return 2

    try:
        usage = _get_json(USAGE_URL, cookie=cookie)
        models_payload = _get_json(MODELS_URL, api_key=args.api_key)
    except urllib.error.HTTPError as e:
        print(f"error: HTTP {e.code} from crof.ai (cookie expired?)", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"error: network failure: {e.reason}", file=sys.stderr)
        return 1

    if not isinstance(usage, dict) or not usage:
        print(f"error: unexpected /user-api/usage response: {usage!r}", file=sys.stderr)
        return 1

    report = compute_report(usage, _build_price_map(models_payload))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
