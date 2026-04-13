"""Tests for project and consumption API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from quota_sentinel.opencode_db import (
    ConsumptionSnapshot,
    ProjectUsageSnapshot,
    SessionStats,
)
from quota_sentinel.server import create_app
from quota_sentinel.config import ServerConfig


# =============================================================================
# Projects Endpoint Tests
# =============================================================================


class TestProjectsEndpoint:
    """Tests for GET /v1/projects."""

    def test_projects_endpoint_requires_auth(self):
        """GET /v1/projects without X-API-Key returns 401."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/projects")
        assert response.status_code == 401

    def test_projects_endpoint_returns_empty_list_when_no_data(self):
        """GET /v1/projects returns empty projects list when no opencode data."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance to get API key
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

        response = client.get("/v1/projects", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        data = response.json()
        assert "projects" in data
        assert data["projects"] == []


class TestProjectDetailEndpoint:
    """Tests for GET /v1/projects/{name}."""

    def test_project_detail_endpoint_requires_auth(self):
        """GET /v1/projects/{name} without X-API-Key returns 401."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/projects/project1")
        assert response.status_code == 401

    def test_project_detail_returns_404_when_not_found(self):
        """GET /v1/projects/{name} returns 404 when project not found."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance to get API key
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

        # Set up the store with empty projects
        from quota_sentinel import server

        store = server._store
        if store:
            store.opencode_projects = []

        response = client.get(
            "/v1/projects/nonexistent", headers={"X-API-Key": api_key}
        )
        assert response.status_code == 404


# =============================================================================
# Consumption Endpoint Tests
# =============================================================================


class TestConsumptionEndpoint:
    """Tests for GET /v1/consumption."""

    def test_consumption_endpoint_requires_auth(self):
        """GET /v1/consumption without X-API-Key returns 401."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/consumption")
        assert response.status_code == 401

    def test_consumption_endpoint_returns_empty_when_no_data(self):
        """GET /v1/consumption returns empty consumption when no data."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance to get API key
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

        response = client.get("/v1/consumption", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert data["providers"] == []


# =============================================================================
# Extended Status Endpoint Tests
# =============================================================================


class TestExtendedInstanceStatus:
    """Tests for extended GET /v1/status/{id} with project token usage."""

    def test_instance_status_includes_project_token_usage(self):
        """GET /v1/status/{id} includes project_token_usage when opencode data available."""
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

        # Set up store with opencode data that matches this project
        from quota_sentinel import server

        store = server._store
        if store:
            store.opencode_projects = [
                ProjectUsageSnapshot(
                    project_path="/home/user/test-project",
                    project_name="test-project",
                    providers={"zai": 5000},
                    total_tokens=5000,
                    session_count=5,
                ),
            ]
            store.opencode_consumption = ConsumptionSnapshot(
                total_tokens=5000,
                by_provider={"zai": 5000},
                by_project={"/home/user/test-project": 5000},
                sessions=[],
            )
            store.opencode_session_stats = []
            store.calibrator = MagicMock()

        response = client.get(
            f"/v1/status/{instance_id}", headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200
        data = response.json()
        # Should have project_token_usage added when opencode data matches project
        assert "project_token_usage" in data
        assert data["project_token_usage"]["total_tokens"] == 5000


class TestExtendedGlobalStatus:
    """Tests for extended GET /v1/status with opencode_source metadata."""

    def test_global_status_includes_opencode_source(self):
        """GET /v1/status includes opencode_source when opencode data available."""
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

        # Set up store with opencode consumption data
        from quota_sentinel import server

        store = server._store
        if store:
            store.opencode_consumption = ConsumptionSnapshot(
                total_tokens=15000,
                by_provider={"zai": 10000, "claude": 5000},
                by_project={},
                sessions=[],
            )
            store.opencode_last_poll = datetime.now(UTC)

        response = client.get("/v1/status", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        data = response.json()
        # Should have opencode_source added
        assert "opencode_source" in data
        assert data["opencode_source"]["total_tokens"] == 15000


# =============================================================================
# Projects Endpoint with Data Tests
# =============================================================================
# Projects Endpoint with Data Tests
# =============================================================================


class TestProjectsEndpointWithData:
    """Tests for GET /v1/projects with opencode data set on real store."""

    def test_projects_endpoint_returns_projects_with_stats(self):
        """GET /v1/projects returns projects with computed stats."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance to get API key
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

        # Set up store with opencode data directly on the module's store
        from quota_sentinel import server

        store = server._store
        if store:
            store.opencode_projects = [
                ProjectUsageSnapshot(
                    project_path="/home/user/project1",
                    project_name="project1",
                    providers={"zai": 5000, "claude": 3000},
                    total_tokens=8000,
                    session_count=10,
                ),
                ProjectUsageSnapshot(
                    project_path="/home/user/project2",
                    project_name="project2",
                    providers={"deepseek": 2000},
                    total_tokens=2000,
                    session_count=5,
                ),
            ]
            store.opencode_session_stats = [
                SessionStats(
                    session_id=1,
                    provider="zai",
                    started_at=datetime.now(UTC),
                    total_tokens=500,
                    message_count=10,
                    assistant_tokens=350,
                    user_tokens=150,
                ),
            ]
            store.calibrator = MagicMock()

        response = client.get("/v1/projects", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        data = response.json()
        assert "projects" in data
        assert len(data["projects"]) == 2


class TestProjectDetailEndpointWithData:
    """Tests for GET /v1/projects/{name} with data on real store."""

    def test_project_detail_returns_project_data(self):
        """GET /v1/projects/{name} returns detailed project data."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance to get API key
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

        # Set up store with opencode data directly
        from quota_sentinel import server

        store = server._store
        if store:
            store.opencode_projects = [
                ProjectUsageSnapshot(
                    project_path="/home/user/project1",
                    project_name="project1",
                    providers={"zai": 5000, "claude": 3000},
                    total_tokens=8000,
                    session_count=10,
                ),
            ]
            store.opencode_session_stats = [
                SessionStats(
                    session_id=1,
                    provider="zai",
                    started_at=datetime.now(UTC),
                    total_tokens=500,
                    message_count=10,
                    assistant_tokens=350,
                    user_tokens=150,
                ),
            ]
            store.calibrator = MagicMock()

        response = client.get("/v1/projects/project1", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        data = response.json()
        assert data["project_name"] == "project1"
        assert data["total_tokens"] == 8000
        assert "providers" in data
        assert data["providers"]["zai"] == 5000


class TestConsumptionEndpointWithData:
    """Tests for GET /v1/consumption with data on real store."""

    def test_consumption_endpoint_returns_provider_stats(self):
        """GET /v1/consumption returns consumption broken down by provider."""
        config = ServerConfig()
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Register instance to get API key
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

        # Set up store with opencode data directly
        from quota_sentinel import server

        store = server._store
        if store:
            store.opencode_consumption = ConsumptionSnapshot(
                total_tokens=10000,
                by_provider={"zai": 6000, "claude": 4000},
                by_project={},
                sessions=[],
            )
            store.opencode_session_stats = [
                SessionStats(
                    session_id=1,
                    provider="zai",
                    started_at=datetime.now(UTC),
                    total_tokens=500,
                    message_count=10,
                    assistant_tokens=350,
                    user_tokens=150,
                ),
                SessionStats(
                    session_id=2,
                    provider="claude",
                    started_at=datetime.now(UTC),
                    total_tokens=800,
                    message_count=15,
                    assistant_tokens=600,
                    user_tokens=200,
                ),
            ]

        response = client.get("/v1/consumption", headers={"X-API-Key": api_key})
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert len(data["providers"]) == 2
        # Check provider data structure
        zai_data = next(p for p in data["providers"] if p["provider"] == "zai")
        assert zai_data["tokens"] == 6000
