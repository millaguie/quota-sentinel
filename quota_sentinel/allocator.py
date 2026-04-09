"""Budget allocator — divides provider caps across active instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quota_sentinel.store import InstanceEntry


class BudgetAllocator:
    """Divides provider caps across active instances."""

    ACTIVE_WEIGHT = 1.0
    IDLE_WEIGHT = 0.3

    def __init__(self, overcommit_factor: float = 1.5):
        self.overcommit_factor = overcommit_factor

    def allocate(
        self,
        instances: list[InstanceEntry],
        base_caps: dict[str, float],
    ) -> dict[str, dict[str, float]]:
        """Compute effective caps per instance.

        Returns {instance_id: {cap_key: effective_cap}}.
        """
        if not instances:
            return {}

        weights: dict[str, float] = {}
        for inst in instances:
            if inst.state == "paused":
                weights[inst.instance_id] = 0.0
            elif inst.state == "idle":
                weights[inst.instance_id] = self.IDLE_WEIGHT
            else:
                weights[inst.instance_id] = self.ACTIVE_WEIGHT

        total_weight = sum(weights.values())
        if total_weight == 0:
            total_weight = float(len(instances))
            weights = {i.instance_id: 1.0 for i in instances}

        allocations: dict[str, dict[str, float]] = {}
        for inst in instances:
            w = weights[inst.instance_id]
            normalized = w / total_weight
            inst_caps: dict[str, float] = {}
            for cap_key, base_val in base_caps.items():
                effective = base_val * normalized * self.overcommit_factor
                inst_caps[cap_key] = min(effective, base_val)
            allocations[inst.instance_id] = inst_caps

        return allocations
