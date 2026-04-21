"""Asyncio polling loop — fetches provider usage at regular intervals."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from quota_sentinel.allocator import BudgetAllocator
from quota_sentinel.config import ServerConfig
from quota_sentinel.engine import VelocityTracker, evaluate
from quota_sentinel.providers.base import UsageResult
from quota_sentinel.store import Store

logger = logging.getLogger(__name__)


def _poll_all_providers(store: Store) -> dict[str, UsageResult]:
    """Fetch all providers synchronously (runs in executor thread).

    Iterates over snapshots of ``store.providers`` because the main asyncio
    thread may mutate the dict (new registrations, deregistrations) while
    this runs in the thread pool. Each provider fetch is wrapped in a
    try/except so one broken provider can't terminate the polling loop.
    """
    results: dict[str, UsageResult] = {}

    # Snapshot to avoid "dictionary changed size during iteration" when
    # registrations happen concurrently on the main thread.
    for _pool_key, pentry in list(store.providers.items()):
        pname = pentry.provider_name
        # Only poll once per provider name (dedup across fingerprints)
        if pname in results:
            pentry.last_result = results[pname]
            continue

        try:
            result = pentry.provider.fetch()
        except Exception as exc:
            logger.exception("  %s: fetch raised unexpectedly", pname)
            result = UsageResult(provider=pname, error=f"fetch crashed: {exc}")

        results[pname] = result
        pentry.last_result = result

        if result.error:
            logger.warning("  %s: ERROR — %s", pname, result.error)
        else:
            # Update velocity trackers
            if pname not in store.velocities:
                store.velocities[pname] = {}
            for wname, wdata in result.windows.items():
                if wname not in store.velocities[pname]:
                    store.velocities[pname][wname] = VelocityTracker(
                        max_samples=store.velocity_window,
                    )
                store.velocities[pname][wname].add(wdata.utilization)

            # Log
            parts = []
            for wn, wd in result.windows.items():
                tracker = store.velocities.get(pname, {}).get(wn)
                vel = tracker.velocity_pct_per_hour() if tracker else 0.0
                vel_str = f" +{vel:.1f}%/h" if vel > 0 else ""
                parts.append(f"{wn}={wd.utilization:.0f}%{vel_str}")
            logger.info("  %s: %s", pname, ", ".join(parts))

    # Propagate results to all entries with same provider name
    for pentry in list(store.providers.values()):
        if pentry.provider_name in results:
            pentry.last_result = results[pentry.provider_name]

    return results


def build_instance_status(
    instance_id: str,
    store: Store,
    config: ServerConfig,
    allocations: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Build TOKEN_STATUS-compatible dict for a single instance."""
    inst = store.instances.get(instance_id)
    if not inst:
        return {"error": "instance not found"}

    # Collect results only for this instance's providers
    inst_results: dict[str, UsageResult] = {}
    for pe in store.providers_for_instance(instance_id):
        if pe.last_result:
            inst_results[pe.provider_name] = pe.last_result

    effective_caps = allocations.get(instance_id, config.hard_caps)

    status = evaluate(
        results=inst_results,
        velocities=store.velocities,
        hard_caps=effective_caps,
        safety_margin_min=config.safety_margin_min,
        framework=inst.framework,
    )

    # Add central metadata
    all_instances = list(store.instances.values())
    total_weight = sum(
        BudgetAllocator.ACTIVE_WEIGHT
        if i.state == "active"
        else BudgetAllocator.IDLE_WEIGHT
        if i.state == "idle"
        else 0.0
        for i in all_instances
    ) or len(all_instances)

    w = (
        BudgetAllocator.ACTIVE_WEIGHT
        if inst.state == "active"
        else BudgetAllocator.IDLE_WEIGHT
        if inst.state == "idle"
        else 0.0
    )

    status["central_watchdog"] = {
        "active_instances": len(all_instances),
        "budget_weight": round(w / total_weight, 2) if total_weight else 0,
        "mode": "centralized",
    }

    return status


async def run_loop(store: Store, config: ServerConfig) -> None:
    """Main polling loop — runs as asyncio task alongside the HTTP server."""
    allocator = BudgetAllocator(overcommit_factor=config.overcommit_factor)
    loop = asyncio.get_event_loop()

    logger.info(
        "Daemon loop started (default poll %ds)",
        config.default_poll_interval,
    )

    while True:
        try:
            # GC dead instances
            timeout_s = (
                store.effective_poll_interval() * config.heartbeat_timeout_factor
            )
            dead = store.gc_dead_instances(timeout_s)
            if dead:
                logger.info("GC pruned: %s", dead)

            if store.providers:
                # Poll in thread pool (providers use sync urllib)
                results = await loop.run_in_executor(None, _poll_all_providers, store)

                # Compute allocations
                instances = list(store.instances.values())
                allocations = allocator.allocate(instances, config.hard_caps)

                # Store allocations for API access
                store._last_allocations = allocations  # noqa: SLF001
                store._last_results = results  # noqa: SLF001

                logger.info(
                    "Poll done: %d providers, %d instances",
                    len(results),
                    len(instances),
                )
            else:
                logger.debug("No providers registered, skipping poll")
        except Exception:
            # Never let an exception terminate the polling loop — log and continue.
            logger.exception("Poll cycle failed, continuing")

        # Sleep with event for forced repoll
        interval = store.effective_poll_interval()
        try:
            await asyncio.wait_for(store.poll_event.wait(), timeout=interval)
            store.poll_event.clear()
            logger.info("Forced repoll triggered")
        except asyncio.TimeoutError:
            pass
