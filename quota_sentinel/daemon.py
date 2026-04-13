"""Asyncio polling loop — fetches provider usage at regular intervals."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from quota_sentinel.allocator import BudgetAllocator
from quota_sentinel.config import ServerConfig
from quota_sentinel.engine import VelocityTracker, evaluate
from quota_sentinel.opencode_db import OpenCodeDBSource
from quota_sentinel.providers.base import UsageResult
from quota_sentinel.store import Store

logger = logging.getLogger(__name__)


def _poll_all_providers(store: Store) -> dict[str, UsageResult]:
    """Fetch all providers synchronously (runs in executor thread)."""
    results: dict[str, UsageResult] = {}

    for _pool_key, pentry in store.providers.items():
        pname = pentry.provider_name
        # Only poll once per provider name (dedup across fingerprints)
        if pname in results:
            pentry.last_result = results[pname]
            continue

        result = pentry.provider.fetch()
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
    for pentry in store.providers.values():
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
        calibrator=store.calibrator,
        session_stats=store.opencode_session_stats,
        sessions_remaining_threshold=config.sessions_remaining_threshold,
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


def _poll_opencode_db(source: OpenCodeDBSource) -> tuple:
    """Fetch OpenCode DB data synchronously (runs in executor thread).

    Returns (consumption, projects, session_stats) or (None, [], []) on error.
    """
    consumption = source.get_consumption_snapshot()
    projects = source.get_project_usage()
    session_stats = source.get_session_stats()
    return consumption, projects, session_stats


def _correlate_projects_with_instances(
    projects: list, instances: list
) -> dict[str, list]:
    """Correlate OpenCode projects (worktree) with registered instances (project_name).

    Returns a mapping of instance_id -> matched project paths.
    """
    correlation: dict[str, list] = {}
    for inst in instances:
        matched = []
        inst_name = inst.project_name.lower()
        for proj in projects:
            proj_path_lower = proj.project_path.lower()
            # Match by project_name in worktree path or exact name match
            if inst_name and (
                inst_name in proj_path_lower or inst_name == proj.project_name.lower()
            ):
                matched.append(proj.project_path)
        if matched:
            correlation[inst.instance_id] = matched
    return correlation


async def _poll_opencode_loop(
    store: Store,
    config: ServerConfig,
) -> None:
    """Independent OpenCode DB polling loop with its own interval."""
    if not config.opencode_db:
        return

    source = OpenCodeDBSource(config.opencode_db)
    interval = config.opencode_poll_interval or 120

    logger.info("OpenCode DB polling loop started (interval %ds)", interval)

    while True:
        try:
            loop = asyncio.get_event_loop()
            consumption, projects, session_stats = await loop.run_in_executor(
                None, _poll_opencode_db, source
            )

            store.update_opencode_data(consumption, projects, session_stats)

            # Correlate instances with projects for logging
            instances = list(store.instances.values())
            correlation = _correlate_projects_with_instances(projects, instances)
            for iid, paths in correlation.items():
                inst = store.instances.get(iid)
                if inst:
                    logger.info(
                        "  OpenCode: instance %s (%s) matched worktrees: %s",
                        iid,
                        inst.project_name,
                        paths,
                    )

            logger.info(
                "OpenCode DB poll done: consumption=%s, projects=%d, sessions=%d",
                consumption.total_tokens if consumption else 0,
                len(projects),
                len(session_stats),
            )
        except Exception as e:
            logger.warning("OpenCode DB polling error: %s — continuing", e)

        await asyncio.sleep(interval)


async def run_loop(store: Store, config: ServerConfig) -> None:
    """Main polling loop — runs as asyncio task alongside the HTTP server."""
    allocator = BudgetAllocator(overcommit_factor=config.overcommit_factor)
    loop = asyncio.get_event_loop()

    logger.info(
        "Daemon loop started (default poll %ds)",
        config.default_poll_interval,
    )

    # Start OpenCode DB polling as independent task if enabled
    opencode_task: asyncio.Task[None] | None = None
    if config.opencode_db:
        opencode_task = asyncio.create_task(_poll_opencode_loop(store, config))

    while True:
        # GC dead instances
        timeout_s = store.effective_poll_interval() * config.heartbeat_timeout_factor
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
            store._last_allocations = allocations
            store._last_results = results

            # Compute calibration if OpenCode DB data is available
            opencode_tokens = (
                store.opencode_consumption.total_tokens
                if store.opencode_consumption
                else 0
            )
            if opencode_tokens > 0:
                calibration = store.compute_calibration(results, opencode_tokens)
                if calibration:
                    logger.info(
                        "Calibration snapshot: %s",
                        calibration,
                    )

            logger.info(
                "Poll done: %d providers, %d instances",
                len(results),
                len(instances),
            )
        else:
            logger.debug("No providers registered, skipping poll")

        # Sleep with event for forced repoll
        interval = store.effective_poll_interval()
        try:
            await asyncio.wait_for(store.poll_event.wait(), timeout=interval)
            store.poll_event.clear()
            logger.info("Forced repoll triggered")
        except asyncio.TimeoutError:
            pass
