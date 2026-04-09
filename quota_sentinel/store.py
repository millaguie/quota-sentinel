"""In-memory state store — instances, provider pool, poll results."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from quota_sentinel.engine import VelocityTracker
from quota_sentinel.providers.base import UsageProvider, UsageResult

logger = logging.getLogger(__name__)


def _fingerprint(provider_name: str, api_key: str) -> str:
    """sha256(provider_name + ':' + api_key)[:16]"""
    return hashlib.sha256(f"{provider_name}:{api_key}".encode()).hexdigest()[:16]


@dataclass
class ProviderEntry:
    """A unique provider+key in the pool."""

    provider: UsageProvider
    provider_name: str
    fingerprint: str
    subscribers: set[str] = field(default_factory=set)  # instance_ids
    last_result: UsageResult | None = None


@dataclass
class InstanceEntry:
    """A registered client instance."""

    instance_id: str
    project_name: str
    framework: str
    poll_interval: int  # seconds
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    heartbeat_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: str = "active"
    provider_fingerprints: list[str] = field(default_factory=list)
    hard_caps: dict[str, float] = field(default_factory=dict)


class Store:
    """Thread-safe in-memory state for the daemon.

    Providers are keyed by "name:fingerprint" to allow deduplication
    when multiple clients register the same key.
    """

    def __init__(self, velocity_window: int = 10):
        self.providers: dict[str, ProviderEntry] = {}  # key: "name:fingerprint"
        self.instances: dict[str, InstanceEntry] = {}  # key: instance_id
        self.velocities: dict[
            str, dict[str, VelocityTracker]
        ] = {}  # provider_name → window → tracker
        self.velocity_window = velocity_window
        self.poll_event = asyncio.Event()
        self._started_at = time.time()

    def uptime(self) -> float:
        return time.time() - self._started_at

    # ── Instance management ─────────────────────────────────────────

    def register_instance(
        self,
        instance_id: str,
        project_name: str,
        framework: str,
        poll_interval: int,
        providers: dict[str, UsageProvider],
        keys: dict[str, str],
        hard_caps: dict[str, float] | None = None,
    ) -> InstanceEntry:
        """Register a client instance with its providers.

        providers: {provider_name: UsageProvider} — already instantiated
        keys: {provider_name: api_key} — for fingerprinting
        """
        fingerprints: list[str] = []

        for pname, provider in providers.items():
            fp = _fingerprint(pname, keys.get(pname, ""))
            pool_key = f"{pname}:{fp}"

            if pool_key in self.providers:
                # Same key already registered — just add subscriber
                self.providers[pool_key].subscribers.add(instance_id)
            else:
                # New provider+key combination
                self.providers[pool_key] = ProviderEntry(
                    provider=provider,
                    provider_name=pname,
                    fingerprint=fp,
                    subscribers={instance_id},
                )
                if pname not in self.velocities:
                    self.velocities[pname] = {}

            fingerprints.append(fp)

        entry = InstanceEntry(
            instance_id=instance_id,
            project_name=project_name,
            framework=framework,
            poll_interval=poll_interval,
            provider_fingerprints=fingerprints,
            hard_caps=hard_caps or {},
        )
        self.instances[instance_id] = entry
        return entry

    def deregister_instance(self, instance_id: str) -> bool:
        """Remove an instance and clean up orphaned providers."""
        inst = self.instances.pop(instance_id, None)
        if not inst:
            return False

        orphaned = []
        for pool_key, pentry in self.providers.items():
            pentry.subscribers.discard(instance_id)
            if not pentry.subscribers:
                orphaned.append(pool_key)

        for pool_key in orphaned:
            pentry = self.providers.pop(pool_key)
            logger.info("Removed orphaned provider %s (no subscribers)", pool_key)
            # Clean up velocity tracker if no other entry for this provider name
            pname = pentry.provider_name
            if not any(e.provider_name == pname for e in self.providers.values()):
                self.velocities.pop(pname, None)

        return True

    def heartbeat(self, instance_id: str, state: str | None = None) -> bool:
        """Update heartbeat timestamp and optionally state."""
        inst = self.instances.get(instance_id)
        if not inst:
            return False
        inst.heartbeat_at = datetime.now(UTC)
        if state:
            inst.state = state
        return True

    # ── Provider pool queries ───────────────────────────────────────

    def providers_for_instance(self, instance_id: str) -> list[ProviderEntry]:
        """Get providers that a specific instance is subscribed to."""
        return [pe for pe in self.providers.values() if instance_id in pe.subscribers]

    def unique_providers(self) -> list[ProviderEntry]:
        """All providers in the pool."""
        return list(self.providers.values())

    def provider_names_for_instance(self, instance_id: str) -> list[str]:
        """Get provider names that a specific instance subscribed."""
        return sorted(
            {
                pe.provider_name
                for pe in self.providers.values()
                if instance_id in pe.subscribers
            }
        )

    # ── Poll control ────────────────────────────────────────────────

    def effective_poll_interval(self) -> int:
        """min(all client poll_intervals) or default 300."""
        if not self.instances:
            return 300
        return min(inst.poll_interval for inst in self.instances.values())

    def trigger_poll(self) -> None:
        """Signal the daemon loop to repoll immediately."""
        self.poll_event.set()

    # ── Garbage collection ──────────────────────────────────────────

    def gc_dead_instances(self, heartbeat_timeout_s: float) -> list[str]:
        """Remove instances that haven't sent a heartbeat in time."""
        now = datetime.now(UTC)
        dead: list[str] = []

        for iid, inst in list(self.instances.items()):
            age = (now - inst.heartbeat_at).total_seconds()
            if age > heartbeat_timeout_s:
                dead.append(iid)
                logger.info(
                    "GC: instance %s (%s) — no heartbeat for %.0fs",
                    iid,
                    inst.project_name,
                    age,
                )

        for iid in dead:
            self.deregister_instance(iid)

        return dead

    # ── Snapshot for API ────────────────────────────────────────────

    def summary(self) -> dict:
        """Global summary for GET /v1/status."""
        return {
            "uptime": round(self.uptime()),
            "instances": len(self.instances),
            "providers": len(self.providers),
            "unique_provider_names": sorted(
                {pe.provider_name for pe in self.providers.values()}
            ),
            "effective_poll_interval": self.effective_poll_interval(),
        }
