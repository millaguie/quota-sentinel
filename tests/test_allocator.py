"""Tests for quota_sentinel.allocator module."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime

from quota_sentinel.allocator import BudgetAllocator
from quota_sentinel.store import InstanceEntry


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def allocator() -> BudgetAllocator:
    """Default allocator with 1.5x overcommit factor."""
    return BudgetAllocator(overcommit_factor=1.5)


@pytest.fixture
def allocator_no_overcommit() -> BudgetAllocator:
    """Allocator with 1.0x overcommit (no overcommit)."""
    return BudgetAllocator(overcommit_factor=1.0)


def make_instance(
    instance_id: str,
    state: str = "active",
    project_name: str = "test-project",
) -> InstanceEntry:
    """Helper to create InstanceEntry with minimal boilerplate."""
    return InstanceEntry(
        instance_id=instance_id,
        project_name=project_name,
        framework="test",
        poll_interval=60,
        registered_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        state=state,
    )


# ── Tests: Empty instances ──────────────────────────────────────────


class TestAllocateEmptyInstances:
    """Tests for allocate() with no instances."""

    def test_returns_empty_dict_when_no_instances(
        self, allocator: BudgetAllocator
    ) -> None:
        """allocate() returns empty dict when instances list is empty."""
        result = allocator.allocate([], {"requests": 1000.0})
        assert result == {}

    def test_returns_empty_dict_with_empty_caps(
        self, allocator: BudgetAllocator
    ) -> None:
        """allocate() returns empty dict when both instances and caps are empty."""
        result = allocator.allocate([], {})
        assert result == {}


# ── Tests: Weight application by state ──────────────────────────────


class TestAllocateWeights:
    """Tests for weight application based on instance state."""

    def test_active_instance_gets_active_weight(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """Active instances get ACTIVE_WEIGHT (1.0)."""
        instances = [make_instance("inst-1", state="active")]
        base_caps = {"requests": 1000.0}

        result = allocator_no_overcommit.allocate(instances, base_caps)

        # Single active instance: weight=1.0, normalized=1.0, effective=1000*1.0*1.0=1000
        assert result["inst-1"]["requests"] == 1000.0

    def test_idle_instance_gets_idle_weight(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """Idle instances get IDLE_WEIGHT (0.3)."""
        instances = [make_instance("inst-1", state="idle")]
        base_caps = {"requests": 1000.0}

        result = allocator_no_overcommit.allocate(instances, base_caps)

        # Single idle instance: weight=0.3, normalized=1.0, effective=1000*1.0*1.0=1000
        # (normalized weight still equals 1.0 since it's the only instance)
        assert result["inst-1"]["requests"] == 1000.0

    def test_paused_instance_gets_zero_weight(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """Paused instances get weight 0."""
        # Need another instance to avoid fallback to equal weights
        instances = [
            make_instance("inst-active", state="active"),
            make_instance("inst-paused", state="paused"),
        ]
        base_caps = {"requests": 1000.0}

        result = allocator_no_overcommit.allocate(instances, base_caps)

        # active=1.0, paused=0.0, total=1.0
        # active normalized: 1.0/1.0 = 1.0 → effective = 1000*1.0*1.0 = 1000
        # paused normalized: 0.0/1.0 = 0.0 → effective = 1000*0.0*1.0 = 0
        assert result["inst-active"]["requests"] == 1000.0
        assert result["inst-paused"]["requests"] == 0.0


# ── Tests: Weight normalization ─────────────────────────────────────


class TestAllocateNormalization:
    """Tests for weight normalization across instances."""

    def test_two_active_instances_split_evenly(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """Two active instances each get 50% of cap."""
        instances = [
            make_instance("inst-1", state="active"),
            make_instance("inst-2", state="active"),
        ]
        base_caps = {"requests": 1000.0}

        result = allocator_no_overcommit.allocate(instances, base_caps)

        # Each active: weight=1.0, total=2.0, normalized=0.5
        # effective = 1000 * 0.5 * 1.0 = 500
        assert result["inst-1"]["requests"] == 500.0
        assert result["inst-2"]["requests"] == 500.0

    def test_active_and_idle_weighted_split(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """Active (1.0) and idle (0.3) instances split proportionally."""
        instances = [
            make_instance("inst-active", state="active"),
            make_instance("inst-idle", state="idle"),
        ]
        base_caps = {"requests": 1000.0}

        result = allocator_no_overcommit.allocate(instances, base_caps)

        # active=1.0, idle=0.3, total=1.3
        # active normalized: 1.0/1.3 ≈ 0.769 → effective ≈ 769.23
        # idle normalized: 0.3/1.3 ≈ 0.231 → effective ≈ 230.77
        total_weight = 1.0 + 0.3
        expected_active = 1000.0 * (1.0 / total_weight)
        expected_idle = 1000.0 * (0.3 / total_weight)

        assert result["inst-active"]["requests"] == pytest.approx(expected_active)
        assert result["inst-idle"]["requests"] == pytest.approx(expected_idle)


# ── Tests: Overcommit factor ────────────────────────────────────────


class TestAllocateOvercommit:
    """Tests for overcommit factor application."""

    def test_overcommit_increases_allocation(self, allocator: BudgetAllocator) -> None:
        """Overcommit factor multiplies the effective cap."""
        instances = [
            make_instance("inst-1", state="active"),
            make_instance("inst-2", state="active"),
        ]
        base_caps = {"requests": 1000.0}

        result = allocator.allocate(instances, base_caps)

        # Each active: normalized=0.5, overcommit=1.5
        # effective = 1000 * 0.5 * 1.5 = 750
        assert result["inst-1"]["requests"] == 750.0
        assert result["inst-2"]["requests"] == 750.0

    def test_overcommit_capped_at_base_value(self, allocator: BudgetAllocator) -> None:
        """Effective cap cannot exceed base cap even with overcommit."""
        instances = [make_instance("inst-1", state="active")]
        base_caps = {"requests": 1000.0}

        result = allocator.allocate(instances, base_caps)

        # Single instance: normalized=1.0, overcommit=1.5
        # effective would be 1000 * 1.0 * 1.5 = 1500, but capped at 1000
        assert result["inst-1"]["requests"] == 1000.0

    def test_custom_overcommit_factor(self) -> None:
        """Custom overcommit factor is applied correctly."""
        allocator = BudgetAllocator(overcommit_factor=2.0)
        instances = [
            make_instance("inst-1", state="active"),
            make_instance("inst-2", state="active"),
        ]
        base_caps = {"requests": 1000.0}

        result = allocator.allocate(instances, base_caps)

        # Each active: normalized=0.5, overcommit=2.0
        # effective = 1000 * 0.5 * 2.0 = 1000 (capped at base)
        assert result["inst-1"]["requests"] == 1000.0
        assert result["inst-2"]["requests"] == 1000.0


# ── Tests: Edge cases ───────────────────────────────────────────────


class TestAllocateEdgeCases:
    """Tests for edge cases and fallback behavior."""

    def test_all_paused_falls_back_to_equal_weights(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """When all instances are paused, fall back to equal weights."""
        instances = [
            make_instance("inst-1", state="paused"),
            make_instance("inst-2", state="paused"),
        ]
        base_caps = {"requests": 1000.0}

        result = allocator_no_overcommit.allocate(instances, base_caps)

        # All paused: total_weight=0, fallback to equal (1.0 each)
        # Each: normalized=0.5, effective=500
        assert result["inst-1"]["requests"] == 500.0
        assert result["inst-2"]["requests"] == 500.0

    def test_single_instance_gets_full_cap(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """Single instance receives the full base cap."""
        instances = [make_instance("inst-solo", state="active")]
        base_caps = {"requests": 1000.0, "tokens": 50000.0}

        result = allocator_no_overcommit.allocate(instances, base_caps)

        assert result["inst-solo"]["requests"] == 1000.0
        assert result["inst-solo"]["tokens"] == 50000.0

    def test_mixed_states_allocation(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """Mixed active, idle, and paused instances are allocated correctly."""
        instances = [
            make_instance("inst-active", state="active"),
            make_instance("inst-idle", state="idle"),
            make_instance("inst-paused", state="paused"),
        ]
        base_caps = {"requests": 1000.0}

        result = allocator_no_overcommit.allocate(instances, base_caps)

        # active=1.0, idle=0.3, paused=0.0, total=1.3
        total_weight = 1.0 + 0.3
        expected_active = 1000.0 * (1.0 / total_weight)
        expected_idle = 1000.0 * (0.3 / total_weight)

        assert result["inst-active"]["requests"] == pytest.approx(expected_active)
        assert result["inst-idle"]["requests"] == pytest.approx(expected_idle)
        assert result["inst-paused"]["requests"] == 0.0

    def test_multiple_caps_allocated(
        self, allocator_no_overcommit: BudgetAllocator
    ) -> None:
        """Multiple cap types are all allocated to each instance."""
        instances = [
            make_instance("inst-1", state="active"),
            make_instance("inst-2", state="active"),
        ]
        base_caps = {
            "requests": 1000.0,
            "tokens": 50000.0,
            "storage_mb": 100.0,
        }

        result = allocator_no_overcommit.allocate(instances, base_caps)

        # Each gets 50% of each cap type
        assert result["inst-1"]["requests"] == 500.0
        assert result["inst-1"]["tokens"] == 25000.0
        assert result["inst-1"]["storage_mb"] == 50.0
        assert result["inst-2"]["requests"] == 500.0
        assert result["inst-2"]["tokens"] == 25000.0
        assert result["inst-2"]["storage_mb"] == 50.0

    def test_empty_caps_returns_empty_instance_caps(
        self, allocator: BudgetAllocator
    ) -> None:
        """When base_caps is empty, instances get empty cap dicts."""
        instances = [make_instance("inst-1", state="active")]
        base_caps: dict[str, float] = {}

        result = allocator.allocate(instances, base_caps)

        assert result["inst-1"] == {}


# ── Tests: BudgetAllocator initialization ───────────────────────────


class TestBudgetAllocatorInit:
    """Tests for BudgetAllocator initialization."""

    def test_default_overcommit_factor(self) -> None:
        """Default overcommit factor is 1.5."""
        allocator = BudgetAllocator()
        assert allocator.overcommit_factor == 1.5

    def test_custom_overcommit_factor(self) -> None:
        """Custom overcommit factor is stored."""
        allocator = BudgetAllocator(overcommit_factor=2.0)
        assert allocator.overcommit_factor == 2.0

    def test_class_constants(self) -> None:
        """Class constants ACTIVE_WEIGHT and IDLE_WEIGHT are correct."""
        assert BudgetAllocator.ACTIVE_WEIGHT == 1.0
        assert BudgetAllocator.IDLE_WEIGHT == 0.3
