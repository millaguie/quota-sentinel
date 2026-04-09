"""Unit tests for quota_sentinel.store module."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from quota_sentinel.store import (
    InstanceEntry,
    ProviderEntry,
    Store,
    _fingerprint,
)
from quota_sentinel.providers.base import UsageProvider, UsageResult


# =============================================================================
# _fingerprint Tests
# =============================================================================


class TestFingerprint:
    """Tests for _fingerprint() function."""

    def test_returns_sha256_prefix(self):
        """Returns sha256 hash of 'provider_name:api_key' truncated to 16 chars."""
        result = _fingerprint("claude", "secret_key_123")
        assert len(result) == 16
        assert isinstance(result, str)

    def test_consistent_for_same_inputs(self):
        """Returns same hash for same provider_name and api_key."""
        result1 = _fingerprint("claude", "my_api_key")
        result2 = _fingerprint("claude", "my_api_key")
        assert result1 == result2

    def test_different_for_different_api_keys(self):
        """Returns different hash for different api_keys."""
        result1 = _fingerprint("claude", "key_one")
        result2 = _fingerprint("claude", "key_two")
        assert result1 != result2

    def test_different_for_different_providers(self):
        """Returns different hash for different provider_names."""
        result1 = _fingerprint("claude", "same_key")
        result2 = _fingerprint("copilot", "same_key")
        assert result1 != result2

    def test_handles_empty_strings(self):
        """Handles empty provider_name and api_key."""
        result = _fingerprint("", "")
        assert len(result) == 16


# =============================================================================
# InstanceEntry Tests
# =============================================================================


class TestInstanceEntry:
    """Tests for InstanceEntry dataclass."""

    def test_default_state_is_active(self):
        """Default state is 'active'."""
        entry = InstanceEntry(
            instance_id="inst-123",
            project_name="test-project",
            framework="opencode",
            poll_interval=60,
        )
        assert entry.state == "active"

    def test_default_registered_at_is_now(self):
        """Default registered_at is close to current time."""
        before = datetime.now(UTC)
        entry = InstanceEntry(
            instance_id="inst-123",
            project_name="test-project",
            framework="opencode",
            poll_interval=60,
        )
        after = datetime.now(UTC)
        assert before <= entry.registered_at <= after

    def test_default_heartbeat_at_is_now(self):
        """Default heartbeat_at is close to current time."""
        before = datetime.now(UTC)
        entry = InstanceEntry(
            instance_id="inst-123",
            project_name="test-project",
            framework="opencode",
            poll_interval=60,
        )
        after = datetime.now(UTC)
        assert before <= entry.heartbeat_at <= after

    def test_default_provider_fingerprints_is_empty_list(self):
        """Default provider_fingerprints is empty list."""
        entry = InstanceEntry(
            instance_id="inst-123",
            project_name="test-project",
            framework="opencode",
            poll_interval=60,
        )
        assert entry.provider_fingerprints == []

    def test_default_hard_caps_is_empty_dict(self):
        """Default hard_caps is empty dict."""
        entry = InstanceEntry(
            instance_id="inst-123",
            project_name="test-project",
            framework="opencode",
            poll_interval=60,
        )
        assert entry.hard_caps == {}

    def test_default_api_key_is_empty_string(self):
        """Default api_key is empty string."""
        entry = InstanceEntry(
            instance_id="inst-123",
            project_name="test-project",
            framework="opencode",
            poll_interval=60,
        )
        assert entry.api_key == ""

    def test_api_key_can_be_set(self):
        """api_key can be set explicitly."""
        entry = InstanceEntry(
            instance_id="inst-123",
            project_name="test-project",
            framework="opencode",
            poll_interval=60,
            api_key="qs_testkey123",
        )
        assert entry.api_key == "qs_testkey123"


# =============================================================================
# ProviderEntry Tests
# =============================================================================


class TestProviderEntry:
    """Tests for ProviderEntry dataclass."""

    def test_has_provider_field(self):
        """Has provider field for UsageProvider."""
        mock_provider = MagicMock(spec=UsageProvider)
        entry = ProviderEntry(
            provider=mock_provider,
            provider_name="claude",
            fingerprint="abc123",
        )
        assert entry.provider is mock_provider

    def test_has_provider_name_field(self):
        """Has provider_name field."""
        mock_provider = MagicMock(spec=UsageProvider)
        entry = ProviderEntry(
            provider=mock_provider,
            provider_name="copilot",
            fingerprint="xyz789",
        )
        assert entry.provider_name == "copilot"

    def test_has_fingerprint_field(self):
        """Has fingerprint field."""
        mock_provider = MagicMock(spec=UsageProvider)
        entry = ProviderEntry(
            provider=mock_provider,
            provider_name="claude",
            fingerprint="fp1234567890abcd",
        )
        assert entry.fingerprint == "fp1234567890abcd"

    def test_default_subscribers_is_empty_set(self):
        """Default subscribers is empty set."""
        mock_provider = MagicMock(spec=UsageProvider)
        entry = ProviderEntry(
            provider=mock_provider,
            provider_name="claude",
            fingerprint="abc123",
        )
        assert entry.subscribers == set()

    def test_default_last_result_is_none(self):
        """Default last_result is None."""
        mock_provider = MagicMock(spec=UsageProvider)
        entry = ProviderEntry(
            provider=mock_provider,
            provider_name="claude",
            fingerprint="abc123",
        )
        assert entry.last_result is None

    def test_can_set_subscribers(self):
        """Can set subscribers explicitly."""
        mock_provider = MagicMock(spec=UsageProvider)
        entry = ProviderEntry(
            provider=mock_provider,
            provider_name="claude",
            fingerprint="abc123",
            subscribers={"inst-1", "inst-2"},
        )
        assert entry.subscribers == {"inst-1", "inst-2"}

    def test_can_set_last_result(self):
        """Can set last_result explicitly."""
        mock_provider = MagicMock(spec=UsageProvider)
        result = UsageResult(provider="claude")
        entry = ProviderEntry(
            provider=mock_provider,
            provider_name="claude",
            fingerprint="abc123",
            last_result=result,
        )
        assert entry.last_result is result


# =============================================================================
# Store Tests
# =============================================================================


class TestStoreInit:
    """Tests for Store.__init__()."""

    def test_initializes_empty_providers(self):
        """Initializes with empty providers dict."""
        store = Store()
        assert store.providers == {}

    def test_initializes_empty_instances(self):
        """Initializes with empty instances dict."""
        store = Store()
        assert store.instances == {}

    def test_initializes_empty_velocities(self):
        """Initializes with empty velocities dict."""
        store = Store()
        assert store.velocities == {}

    def test_initializes_poll_event(self):
        """Initializes poll_event as asyncio.Event."""
        store = Store()
        assert isinstance(store.poll_event, asyncio.Event)

    def test_accepts_velocity_window_parameter(self):
        """Accepts velocity_window parameter."""
        store = Store(velocity_window=20)
        assert store.velocity_window == 20

    def test_default_velocity_window_is_10(self):
        """Default velocity_window is 10."""
        store = Store()
        assert store.velocity_window == 10


class TestStoreUptime:
    """Tests for Store.uptime() method."""

    def test_returns_elapsed_time(self):
        """Returns elapsed time since store creation."""
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000.0
            store = Store()
            mock_time.return_value = 1005.0
            uptime = store.uptime()
        assert uptime == 5.0

    def test_increases_over_time(self):
        """Uptime increases over time."""
        store = Store()
        uptime1 = store.uptime()
        time.sleep(0.01)
        uptime2 = store.uptime()
        assert uptime2 > uptime1


class TestStoreRegisterInstance:
    """Tests for Store.register_instance() method."""

    def test_creates_instance_entry(self):
        """Creates InstanceEntry with correct fields."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        entry = store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=120,
            providers={"claude": mock_provider},
            keys={"claude": "api_key_123"},
        )

        assert entry.instance_id == "inst-123"
        assert entry.project_name == "my-project"
        assert entry.framework == "opencode"
        assert entry.poll_interval == 120
        assert "inst-123" in store.instances

    def test_creates_provider_entry(self):
        """Creates ProviderEntry for each provider."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key_123"},
        )

        assert len(store.providers) == 1
        provider_entry = list(store.providers.values())[0]
        assert provider_entry.provider is mock_provider
        assert provider_entry.provider_name == "claude"
        assert "inst-123" in provider_entry.subscribers

    def test_creates_velocity_tracker_dict_for_provider(self):
        """Creates velocity tracker dict for new provider name."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key_123"},
        )

        assert "claude" in store.velocities

    def test_deduplicates_same_key_adds_subscriber(self):
        """Same provider+key adds subscriber instead of creating new entry."""
        store = Store()
        mock_provider1 = MagicMock(spec=UsageProvider)
        mock_provider2 = MagicMock(spec=UsageProvider)

        # First instance registers
        store.register_instance(
            instance_id="inst-1",
            project_name="project-1",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider1},
            keys={"claude": "shared_key"},
        )

        # Second instance registers with same key
        store.register_instance(
            instance_id="inst-2",
            project_name="project-2",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider2},
            keys={"claude": "shared_key"},
        )

        # Should still have only one provider entry
        assert len(store.providers) == 1
        # Both instances should be subscribers
        provider_entry = list(store.providers.values())[0]
        assert provider_entry.subscribers == {"inst-1", "inst-2"}

    def test_different_keys_create_separate_entries(self):
        """Different api_keys create separate provider entries."""
        store = Store()
        mock_provider1 = MagicMock(spec=UsageProvider)
        mock_provider2 = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-1",
            project_name="project-1",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider1},
            keys={"claude": "key_one"},
        )

        store.register_instance(
            instance_id="inst-2",
            project_name="project-2",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider2},
            keys={"claude": "key_two"},
        )

        # Should have two provider entries
        assert len(store.providers) == 2

    def test_stores_hard_caps(self):
        """Stores hard_caps in instance entry."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        caps = {"claude_hourly": 80.0, "claude_daily": 90.0}

        entry = store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
            hard_caps=caps,
        )

        assert entry.hard_caps == caps

    def test_hard_caps_defaults_to_empty_dict(self):
        """hard_caps defaults to empty dict when not provided."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        entry = store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        assert entry.hard_caps == {}

    def test_generates_api_key_on_registration(self):
        """Generates api_key with qs_ prefix and 32 random chars."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        entry = store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        assert entry.api_key.startswith("qs_")
        # qs_ prefix (3 chars) + 32 random chars = 35 total minimum
        assert len(entry.api_key) >= 35

    def test_api_keys_are_unique_per_registration(self):
        """Each registration gets a unique api_key."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        entry1 = store.register_instance(
            instance_id="inst-1",
            project_name="project-1",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key_1"},
        )

        entry2 = store.register_instance(
            instance_id="inst-2",
            project_name="project-2",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key_2"},
        )

        assert entry1.api_key != entry2.api_key

    def test_stores_provider_fingerprints_in_entry(self):
        """Stores provider fingerprints in instance entry."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        entry = store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key_123"},
        )

        assert len(entry.provider_fingerprints) == 1
        assert entry.provider_fingerprints[0] == _fingerprint("claude", "api_key_123")

    def test_multiple_providers_registered(self):
        """Can register instance with multiple providers."""
        store = Store()
        mock_claude = MagicMock(spec=UsageProvider)
        mock_copilot = MagicMock(spec=UsageProvider)

        entry = store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_claude, "copilot": mock_copilot},
            keys={"claude": "claude_key", "copilot": "copilot_key"},
        )

        assert len(store.providers) == 2
        assert len(entry.provider_fingerprints) == 2


class TestStoreDeregisterInstance:
    """Tests for Store.deregister_instance() method."""

    def test_returns_false_if_instance_not_found(self):
        """Returns False if instance_id not in store."""
        store = Store()
        result = store.deregister_instance("nonexistent-id")
        assert result is False

    def test_returns_true_on_successful_deregister(self):
        """Returns True on successful deregistration."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        result = store.deregister_instance("inst-123")
        assert result is True

    def test_removes_instance_from_store(self):
        """Removes instance from instances dict."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        store.deregister_instance("inst-123")
        assert "inst-123" not in store.instances

    def test_removes_orphaned_provider(self):
        """Removes provider when no more subscribers."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        store.deregister_instance("inst-123")
        assert len(store.providers) == 0

    def test_keeps_provider_with_other_subscribers(self):
        """Keeps provider when other instances still subscribed."""
        store = Store()
        mock_provider1 = MagicMock(spec=UsageProvider)
        mock_provider2 = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-1",
            project_name="project-1",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider1},
            keys={"claude": "shared_key"},
        )
        store.register_instance(
            instance_id="inst-2",
            project_name="project-2",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider2},
            keys={"claude": "shared_key"},
        )

        store.deregister_instance("inst-1")

        # Provider should still exist with inst-2 as subscriber
        assert len(store.providers) == 1
        provider_entry = list(store.providers.values())[0]
        assert provider_entry.subscribers == {"inst-2"}

    def test_cleans_up_velocity_tracker_when_no_providers_left(self):
        """Removes velocity tracker when no providers of that name left."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        assert "claude" in store.velocities
        store.deregister_instance("inst-123")
        assert "claude" not in store.velocities

    def test_keeps_velocity_tracker_for_other_provider_entries(self):
        """Keeps velocity tracker when other provider entries exist for that name."""
        store = Store()
        mock_provider1 = MagicMock(spec=UsageProvider)
        mock_provider2 = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-1",
            project_name="project-1",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider1},
            keys={"claude": "key_one"},
        )
        store.register_instance(
            instance_id="inst-2",
            project_name="project-2",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider2},
            keys={"claude": "key_two"},  # Different key
        )

        store.deregister_instance("inst-1")

        # Velocity tracker for claude should still exist
        assert "claude" in store.velocities


class TestStoreHeartbeat:
    """Tests for Store.heartbeat() method."""

    def test_returns_false_if_instance_not_found(self):
        """Returns False if instance_id not in store."""
        store = Store()
        result = store.heartbeat("nonexistent-id")
        assert result is False

    def test_returns_true_on_successful_heartbeat(self):
        """Returns True on successful heartbeat."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        result = store.heartbeat("inst-123")
        assert result is True

    def test_updates_heartbeat_timestamp(self):
        """Updates heartbeat_at to current time."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        old_heartbeat = store.instances["inst-123"].heartbeat_at
        time.sleep(0.01)
        store.heartbeat("inst-123")
        new_heartbeat = store.instances["inst-123"].heartbeat_at

        assert new_heartbeat > old_heartbeat

    def test_updates_state_when_provided(self):
        """Updates state when state parameter is provided."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        store.heartbeat("inst-123", state="paused")
        assert store.instances["inst-123"].state == "paused"

    def test_keeps_state_when_not_provided(self):
        """Keeps existing state when state parameter is None."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        original_state = store.instances["inst-123"].state
        store.heartbeat("inst-123")
        assert store.instances["inst-123"].state == original_state


class TestStoreProvidersForInstance:
    """Tests for Store.providers_for_instance() method."""

    def test_returns_providers_for_instance(self):
        """Returns list of ProviderEntry for given instance."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)
        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        providers = store.providers_for_instance("inst-123")
        assert len(providers) == 1
        assert providers[0].provider_name == "claude"

    def test_returns_empty_list_for_unknown_instance(self):
        """Returns empty list for unknown instance_id."""
        store = Store()
        providers = store.providers_for_instance("nonexistent")
        assert providers == []

    def test_returns_only_subscribed_providers(self):
        """Returns only providers the instance is subscribed to."""
        store = Store()
        mock_claude = MagicMock(spec=UsageProvider)
        mock_copilot = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-1",
            project_name="project-1",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_claude},
            keys={"claude": "claude_key"},
        )
        store.register_instance(
            instance_id="inst-2",
            project_name="project-2",
            framework="opencode",
            poll_interval=60,
            providers={"copilot": mock_copilot},
            keys={"copilot": "copilot_key"},
        )

        providers_inst1 = store.providers_for_instance("inst-1")
        assert len(providers_inst1) == 1
        assert providers_inst1[0].provider_name == "claude"

        providers_inst2 = store.providers_for_instance("inst-2")
        assert len(providers_inst2) == 1
        assert providers_inst2[0].provider_name == "copilot"


class TestStoreUniqueProviders:
    """Tests for Store.unique_providers() method."""

    def test_returns_all_providers(self):
        """Returns list of all provider entries."""
        store = Store()
        mock_claude = MagicMock(spec=UsageProvider)
        mock_copilot = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_claude, "copilot": mock_copilot},
            keys={"claude": "claude_key", "copilot": "copilot_key"},
        )

        providers = store.unique_providers()
        assert len(providers) == 2
        names = {p.provider_name for p in providers}
        assert names == {"claude", "copilot"}

    def test_returns_empty_list_when_no_providers(self):
        """Returns empty list when no providers registered."""
        store = Store()
        providers = store.unique_providers()
        assert providers == []


class TestStoreProviderNamesForInstance:
    """Tests for Store.provider_names_for_instance() method."""

    def test_returns_sorted_provider_names(self):
        """Returns sorted list of provider names for instance."""
        store = Store()
        mock_claude = MagicMock(spec=UsageProvider)
        mock_copilot = MagicMock(spec=UsageProvider)
        mock_deepseek = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={
                "deepseek": mock_deepseek,
                "claude": mock_claude,
                "copilot": mock_copilot,
            },
            keys={
                "deepseek": "dk_key",
                "claude": "claude_key",
                "copilot": "copilot_key",
            },
        )

        names = store.provider_names_for_instance("inst-123")
        assert names == ["claude", "copilot", "deepseek"]

    def test_returns_empty_list_for_unknown_instance(self):
        """Returns empty list for unknown instance_id."""
        store = Store()
        names = store.provider_names_for_instance("nonexistent")
        assert names == []


class TestStoreEffectivePollInterval:
    """Tests for Store.effective_poll_interval() method."""

    def test_returns_300_when_no_instances(self):
        """Returns 300 (default) when no instances registered."""
        store = Store()
        interval = store.effective_poll_interval()
        assert interval == 300

    def test_returns_min_poll_interval(self):
        """Returns minimum poll_interval from all instances."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-1",
            project_name="project-1",
            framework="opencode",
            poll_interval=120,
            providers={"claude": mock_provider},
            keys={"claude": "key_1"},
        )
        store.register_instance(
            instance_id="inst-2",
            project_name="project-2",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "key_2"},
        )
        store.register_instance(
            instance_id="inst-3",
            project_name="project-3",
            framework="opencode",
            poll_interval=180,
            providers={"claude": mock_provider},
            keys={"claude": "key_3"},
        )

        interval = store.effective_poll_interval()
        assert interval == 60


class TestStoreTriggerPoll:
    """Tests for Store.trigger_poll() method."""

    def test_sets_poll_event(self):
        """Sets poll_event to trigger immediate poll."""
        store = Store()
        assert not store.poll_event.is_set()
        store.trigger_poll()
        assert store.poll_event.is_set()


class TestStoreGcDeadInstances:
    """Tests for Store.gc_dead_instances() method."""

    def test_removes_instances_without_recent_heartbeat(self):
        """Removes instances that haven't sent heartbeat in timeout period."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        # Manually set heartbeat to old time
        store.instances["inst-123"].heartbeat_at = datetime.now(UTC) - timedelta(
            seconds=120
        )

        dead = store.gc_dead_instances(heartbeat_timeout_s=60)

        assert dead == ["inst-123"]
        assert "inst-123" not in store.instances

    def test_keeps_instances_with_recent_heartbeat(self):
        """Keeps instances that have sent heartbeat within timeout."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        dead = store.gc_dead_instances(heartbeat_timeout_s=60)

        assert dead == []
        assert "inst-123" in store.instances

    def test_returns_list_of_removed_instance_ids(self):
        """Returns list of removed instance IDs."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-1",
            project_name="project-1",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "key_1"},
        )
        store.register_instance(
            instance_id="inst-2",
            project_name="project-2",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "key_2"},
        )

        # Make inst-1 dead
        store.instances["inst-1"].heartbeat_at = datetime.now(UTC) - timedelta(
            seconds=120
        )

        dead = store.gc_dead_instances(heartbeat_timeout_s=60)

        assert dead == ["inst-1"]

    def test_removes_orphaned_providers_after_gc(self):
        """Removes orphaned providers when instances are garbage collected."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        store.instances["inst-123"].heartbeat_at = datetime.now(UTC) - timedelta(
            seconds=120
        )

        store.gc_dead_instances(heartbeat_timeout_s=60)

        assert len(store.providers) == 0


class TestStoreSummary:
    """Tests for Store.summary() method."""

    def test_returns_dict_with_uptime(self):
        """Returns dict containing uptime."""
        store = Store()
        summary = store.summary()
        assert "uptime" in summary
        assert isinstance(summary["uptime"], int)

    def test_returns_dict_with_instances_count(self):
        """Returns dict containing instances count."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        summary = store.summary()
        assert summary["instances"] == 1

    def test_returns_dict_with_providers_count(self):
        """Returns dict containing providers count."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"claude": mock_provider, "copilot": mock_provider},
            keys={"claude": "key1", "copilot": "key2"},
        )

        summary = store.summary()
        assert summary["providers"] == 2

    def test_returns_dict_with_unique_provider_names(self):
        """Returns dict containing sorted unique provider names."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=60,
            providers={"copilot": mock_provider, "claude": mock_provider},
            keys={"copilot": "key1", "claude": "key2"},
        )

        summary = store.summary()
        assert summary["unique_provider_names"] == ["claude", "copilot"]

    def test_returns_dict_with_effective_poll_interval(self):
        """Returns dict containing effective_poll_interval."""
        store = Store()
        mock_provider = MagicMock(spec=UsageProvider)

        store.register_instance(
            instance_id="inst-123",
            project_name="my-project",
            framework="opencode",
            poll_interval=45,
            providers={"claude": mock_provider},
            keys={"claude": "api_key"},
        )

        summary = store.summary()
        assert summary["effective_poll_interval"] == 45

    def test_empty_store_summary(self):
        """Returns correct summary for empty store."""
        store = Store()
        summary = store.summary()

        assert summary["instances"] == 0
        assert summary["providers"] == 0
        assert summary["unique_provider_names"] == []
        assert summary["effective_poll_interval"] == 300
