"""Extended tests for quota_sentinel.server module — API handler tests."""

from __future__ import annotations

from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

from quota_sentinel.server import create_app, _build_providers_from_auth
from quota_sentinel.config import ServerConfig
from quota_sentinel.store import InstanceEntry


# =============================================================================
# Registration Handler Tests
# =============================================================================


class TestRegistrationValidation:
    """Tests for registration input validation."""

    def test_register_with_invalid_json_returns_400(self):
        """POST /v1/instances with invalid JSON returns 400."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/instances",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert "invalid JSON" in response.json()["error"]

    def test_register_without_project_name_returns_400(self):
        """POST /v1/instances without project_name returns 400."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/instances",
            json={
                "project_name": "",
                "auth": {
                    "opencode_auth": {
                        "zai-coding-plan": {"key": "test-key"},
                    },
                },
            },
        )
        assert response.status_code == 400
        assert "project_name required" in response.json()["error"]

    def test_register_without_auth_returns_400(self):
        """POST /v1/instances without auth returns 400."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {},
            },
        )
        assert response.status_code == 400
        assert "auth required" in response.json()["error"]

    def test_register_with_no_valid_providers_returns_400(self):
        """POST /v1/instances with no valid providers returns 400."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {
                    "opencode_auth": {
                        "unknown-provider": {"key": "test-key"},
                    },
                },
            },
        )
        assert response.status_code == 400
        assert "no valid providers" in response.json()["error"]


class TestBuildProvidersFromAuth:
    """Tests for _build_providers_from_auth function."""

    def test_creates_zai_provider_from_opencode_auth(self):
        """Test zai provider is created from opencode_auth."""
        auth = {
            "opencode_auth": {
                "zai-coding-plan": {"key": "sk-test-key"},
            },
        }
        providers, keys = _build_providers_from_auth(auth, {})
        assert "zai" in providers
        assert keys["zai"] == "sk-test-key"

    def test_creates_claude_provider_from_credentials(self):
        """Test claude provider is created from claude_credentials."""
        auth = {
            "claude_credentials": {
                "accessToken": "access-token-123",
                "refreshToken": "refresh-token-456",
                "expiresAt": 9999999999999,
            },
        }
        providers, keys = _build_providers_from_auth(auth, {})
        assert "claude" in providers
        assert keys["claude"] == "access-token-123"

    def test_creates_copilot_provider_from_github_token(self):
        """Test copilot provider is created from github_token."""
        auth = {
            "github_token": "gho_test_token",
        }
        provider_config = {
            "copilot": {
                "github_username": "testuser",
                "plan": "pro",
            }
        }
        providers, keys = _build_providers_from_auth(auth, provider_config)
        assert "copilot" in providers
        assert keys["copilot"] == "gho_test_token"

    def test_skips_invalid_opencode_auth_entries(self):
        """Test that invalid opencode auth entries are skipped."""
        auth = {
            "opencode_auth": {
                "zai-coding-plan": {},  # missing key
                "unknown-provider": {"key": "test"},  # unknown provider
            },
        }
        providers, keys = _build_providers_from_auth(auth, {})
        assert len(providers) == 0

    def test_skips_copilot_without_username(self):
        """Test copilot is skipped when github_username is empty."""
        auth = {
            "github_token": "gho_token",
        }
        provider_config = {
            "copilot": {
                "github_username": "",
                "plan": "pro",
            }
        }
        providers, keys = _build_providers_from_auth(auth, provider_config)
        assert "copilot" not in providers

    def test_merges_provider_config_with_auth(self):
        """Test provider config is merged with auth config."""
        auth = {
            "opencode_auth": {
                "minimax-coding-plan": {"key": "token123"},
            },
        }
        provider_config = {
            "minimax": {
                "group_id": "group-abc",
            }
        }
        providers, keys = _build_providers_from_auth(auth, provider_config)
        assert "minimax" in providers


# =============================================================================
# Deregister Instance Tests
# =============================================================================


class TestDeregisterInstance:
    """Tests for DELETE /v1/instances/{id}."""

    def test_deregister_existing_instance_returns_200(self):
        """DELETE /v1/instances/{id} with existing instance returns 200."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # First register an instance
        register_response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {
                    "opencode_auth": {
                        "zai-coding-plan": {"key": "test-key-123"},
                    },
                },
            },
        )
        instance_id = register_response.json()["instance_id"]

        # Now deregister it
        response = client.delete(f"/v1/instances/{instance_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_deregister_nonexistent_instance_returns_404(self):
        """DELETE /v1/instances/{id} with unknown instance returns 404."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/v1/instances/nonexistent-id")
        assert response.status_code == 404
        assert "not found" in response.json()["error"]


# =============================================================================
# Instance Status Tests
# =============================================================================


class TestInstanceStatus:
    """Tests for GET /v1/status/{id}."""

    def test_instance_status_returns_404_for_unknown_instance(self):
        """GET /v1/status/{id} with unknown instance returns 404."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/status/nonexistent-id")
        assert response.status_code == 404
        assert "not found" in response.json()["error"]


# =============================================================================
# Provider Detail Tests
# =============================================================================


class TestProviderDetail:
    """Tests for GET /v1/providers/{name}."""

    def test_provider_detail_returns_404_for_unknown_provider(self):
        """GET /v1/providers/{name} with unknown provider returns 404."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/providers/unknown-provider")
        assert response.status_code == 404
        assert "not found" in response.json()["error"]


# =============================================================================
# Global Status Tests
# =============================================================================


class TestGlobalStatus:
    """Tests for GET /v1/status."""

    def test_global_status_includes_allocations(self):
        """GET /v1/status includes allocations in response."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register an instance
        register_response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {
                    "opencode_auth": {
                        "zai-coding-plan": {"key": "test-key-123"},
                    },
                },
            },
        )
        api_key = register_response.json()["api_key"]

        # Access status
        response = client.get("/v1/status", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        data = response.json()
        assert "allocations" in data
        assert "instances" in data
        assert "providers" in data


# =============================================================================
# Health Endpoint Tests
# =============================================================================


class TestHealthEndpoint:
    """Extended health endpoint tests."""

    def test_health_returns_uptime(self):
        """GET /v1/health returns uptime information."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "uptime" in data
        assert "providers" in data
        assert "instances" in data
        assert data["status"] == "ok"


# =============================================================================
# Heartbeat Tests
# =============================================================================


class TestHeartbeat:
    """Extended heartbeat tests."""

    def test_heartbeat_with_unknown_instance_returns_404(self):
        """PATCH heartbeat with unknown instance returns 404 after auth."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # First register an instance to get a valid API key
        register_response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {
                    "opencode_auth": {
                        "zai-coding-plan": {"key": "test-key-123"},
                    },
                },
            },
        )
        api_key = register_response.json()["api_key"]

        # Now try to heartbeat with a non-existent instance ID using the valid key
        response = client.patch(
            "/v1/instances/unknown-id/heartbeat",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 404

    def test_heartbeat_with_state_update(self):
        """PATCH heartbeat can update instance state."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance
        register_response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {
                    "opencode_auth": {
                        "zai-coding-plan": {"key": "test-key-123"},
                    },
                },
            },
        )
        instance_id = register_response.json()["instance_id"]
        api_key = register_response.json()["api_key"]

        # Update state to idle
        response = client.patch(
            f"/v1/instances/{instance_id}/heartbeat",
            headers={"X-API-Key": api_key},
            json={"state": "idle"},
        )
        assert response.status_code == 200

    def test_heartbeat_with_empty_body(self):
        """PATCH heartbeat with empty body doesn't error."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance
        register_response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {
                    "opencode_auth": {
                        "zai-coding-plan": {"key": "test-key-123"},
                    },
                },
            },
        )
        instance_id = register_response.json()["instance_id"]
        api_key = register_response.json()["api_key"]

        # Send empty body
        response = client.patch(
            f"/v1/instances/{instance_id}/heartbeat",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200


# =============================================================================
# Providers Summary Tests
# =============================================================================


class TestProvidersSummary:
    """Tests for GET /v1/providers."""

    def test_providers_summary_returns_unknown_for_unpolled_provider(self):
        """GET /v1/providers returns UNKNOWN for providers without data."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance
        register_response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {
                    "opencode_auth": {
                        "zai-coding-plan": {"key": "test-key-123"},
                    },
                },
            },
        )
        api_key = register_response.json()["api_key"]

        response = client.get("/v1/providers", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        data = response.json()
        # Provider should be UNKNOWN since we haven't polled yet
        assert "zai" in data
        assert data["zai"]["status"] == "UNKNOWN"


# =============================================================================
# Poll Trigger Tests
# =============================================================================


class TestPollTrigger:
    """Tests for POST /v1/poll."""

    def test_poll_trigger_returns_success(self):
        """POST /v1/poll returns success status."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance
        register_response = client.post(
            "/v1/instances",
            json={
                "project_name": "test-project",
                "auth": {
                    "opencode_auth": {
                        "zai-coding-plan": {"key": "test-key-123"},
                    },
                },
            },
        )
        api_key = register_response.json()["api_key"]

        response = client.post("/v1/poll", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        assert "poll triggered" in response.json()["status"]
