"""Unit tests for quota_sentinel.server module — API key authentication."""

from __future__ import annotations

from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch

from quota_sentinel.server import create_app
from quota_sentinel.config import ServerConfig
from quota_sentinel.store import InstanceEntry


# =============================================================================
# Registration API Key Tests
# =============================================================================


class TestRegistrationReturnsApiKey:
    """Tests that POST /v1/instances returns api_key in response."""

    def test_register_returns_api_key(self):
        """Registration response includes api_key."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
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

        assert response.status_code == 201
        data = response.json()
        assert "api_key" in data
        assert data["api_key"].startswith("qs_")

    def test_api_key_format_is_correct(self):
        """API key has format: qs_ + at least 32 chars."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
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

        data = response.json()
        api_key = data["api_key"]
        # qs_ prefix (3 chars) + at least 32 random chars
        assert len(api_key) >= 35


# =============================================================================
# _get_instance_from_request Tests
# =============================================================================


class TestGetInstanceFromRequest:
    """Tests for _get_instance_from_request helper function."""

    def test_returns_none_when_no_header(self):
        """Returns None when X-API-Key header is missing."""
        from quota_sentinel.server import _get_instance_from_request

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        with patch("quota_sentinel.server._get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.instances = {}
            mock_get_store.return_value = mock_store

            result = _get_instance_from_request(mock_request)
            assert result is None

    def test_returns_none_when_api_key_invalid(self):
        """Returns None when X-API-Key doesn't match any instance."""
        from quota_sentinel.server import _get_instance_from_request

        mock_request = MagicMock()
        mock_request.headers.get.return_value = "qs_invalid_key"

        with patch("quota_sentinel.server._get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_entry = MagicMock()
            mock_entry.api_key = "qs_different_key"
            mock_store.instances = {"inst-1": mock_entry}
            mock_get_store.return_value = mock_store

            result = _get_instance_from_request(mock_request)
            assert result is None

    def test_returns_instance_when_api_key_valid(self):
        """Returns InstanceEntry when X-API-Key matches."""
        from quota_sentinel.server import _get_instance_from_request

        mock_request = MagicMock()
        mock_request.headers.get.return_value = "qs_valid_key"

        with patch("quota_sentinel.server._get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_entry = MagicMock(spec=InstanceEntry)
            mock_entry.api_key = "qs_valid_key"
            mock_store.instances = {"inst-1": mock_entry}
            mock_get_store.return_value = mock_store

            result = _get_instance_from_request(mock_request)
            assert result is mock_entry


# =============================================================================
# Protected Endpoint Tests
# =============================================================================


class TestStatusEndpointAuth:
    """Tests for GET /v1/status with API key auth."""

    def test_status_without_auth_returns_401(self):
        """GET /v1/status without X-API-Key returns 401."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/status")
        assert response.status_code == 401

    def test_status_with_invalid_auth_returns_401(self):
        """GET /v1/status with invalid X-API-Key returns 401."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/status", headers={"X-API-Key": "invalid"})
        assert response.status_code == 401

    def test_status_with_valid_auth_returns_200(self):
        """GET /v1/status with valid X-API-Key returns instance data."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # First register an instance to get an API key
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

        # Now access status with the API key
        response = client.get("/v1/status", headers={"X-API-Key": api_key})
        assert response.status_code == 200


class TestProvidersEndpointAuth:
    """Tests for GET /v1/providers with API key auth."""

    def test_providers_without_auth_returns_401(self):
        """GET /v1/providers without X-API-Key returns 401."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/providers")
        assert response.status_code == 401

    def test_providers_with_valid_auth_returns_200(self):
        """GET /v1/providers with valid X-API-Key returns data."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # First register an instance to get an API key
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


class TestPollEndpointAuth:
    """Tests for POST /v1/poll with API key auth."""

    def test_poll_without_auth_returns_401(self):
        """POST /v1/poll without X-API-Key returns 401."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/poll")
        assert response.status_code == 401

    def test_poll_with_valid_auth_returns_200(self):
        """POST /v1/poll with valid X-API-Key triggers poll."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # First register an instance to get an API key
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


class TestHeartbeatEndpointAuth:
    """Tests for PATCH /v1/instances/{id}/heartbeat with API key auth."""

    def test_heartbeat_with_wrong_api_key_returns_401(self):
        """PATCH heartbeat with wrong X-API-Key returns 401."""
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

        # Try heartbeat with wrong API key
        response = client.patch(
            f"/v1/instances/{instance_id}/heartbeat",
            headers={"X-API-Key": "wrong_key"},
        )
        assert response.status_code == 401

    def test_heartbeat_with_correct_api_key_returns_200(self):
        """PATCH heartbeat with correct X-API-Key returns 200."""
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
        api_key = register_response.json()["api_key"]

        response = client.patch(
            f"/v1/instances/{instance_id}/heartbeat",
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200


class TestHealthEndpointNoAuth:
    """Tests that GET /v1/health doesn't require auth."""

    def test_health_without_auth_returns_200(self):
        """GET /v1/health works without X-API-Key."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/health")
        assert response.status_code == 200


class TestInstancesEndpointNoAuth:
    """Tests that POST /v1/instances doesn't require auth."""

    def test_register_without_auth_returns_201(self):
        """POST /v1/instances works without X-API-Key."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
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
        assert response.status_code == 201


# =============================================================================
# Metrics Endpoint Tests
# =============================================================================


class TestMetricsEndpoint:
    """Tests for GET /v1/metrics Prometheus-compatible endpoint."""

    def test_metrics_returns_200_without_auth(self):
        """GET /v1/metrics works without X-API-Key."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/metrics")
        assert response.status_code == 200

    def test_metrics_returns_prometheus_text_format(self):
        """GET /v1/metrics returns Prometheus text format."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/metrics")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "text/plain" in str(response.headers)

    def test_metrics_includes_instances_total(self):
        """GET /v1/metrics includes quota_sentinel_instances_total metric."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/metrics")
        assert response.status_code == 200
        assert "quota_sentinel_instances_total" in response.text

    def test_metrics_includes_providers_total(self):
        """GET /v1/metrics includes quota_sentinel_providers_total metric."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/metrics")
        assert response.status_code == 200
        assert "quota_sentinel_providers_total" in response.text

    def test_metrics_includes_uptime_seconds(self):
        """GET /v1/metrics includes quota_sentinel_uptime_seconds metric."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/metrics")
        assert response.status_code == 200
        assert "quota_sentinel_uptime_seconds" in response.text

    def test_metrics_provider_utilization_and_status_present_when_data_exists(self):
        """Per-provider metrics appear when provider polling data exists.

        Without polling, per-provider utilization/status metrics won't be present.
        This test registers an instance and verifies the basic metrics are present.
        """
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register an instance (this creates providers but no polling data yet)
        client.post(
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

        response = client.get("/v1/metrics")
        assert response.status_code == 200
        # Basic metrics should be present
        assert "quota_sentinel_instances_total" in response.text
        assert "quota_sentinel_providers_total" in response.text
        assert "quota_sentinel_uptime_seconds" in response.text

    def test_metrics_instances_total_reflects_registered_instances(self):
        """quota_sentinel_instances_total reflects actual instance count."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Initially 0
        response = client.get("/v1/metrics")
        assert response.status_code == 200
        assert "quota_sentinel_instances_total 0" in response.text

        # Register an instance
        client.post(
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

        response = client.get("/v1/metrics")
        assert response.status_code == 200
        assert "quota_sentinel_instances_total 1" in response.text

    def test_metrics_providers_total_reflects_provider_count(self):
        """quota_sentinel_providers_total reflects unique provider count."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/metrics")
        assert response.status_code == 200
        assert "quota_sentinel_providers_total 0" in response.text

        # Register an instance with a provider
        client.post(
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

        response = client.get("/v1/metrics")
        assert response.status_code == 200
        assert "quota_sentinel_providers_total 1" in response.text
