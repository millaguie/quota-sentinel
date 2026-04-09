"""Pytest configuration for quota-sentinel tests."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# Mock HTTP calls for provider tests
@pytest.fixture
def mock_http_response():
    """Fixture to mock HTTP responses."""

    def _mock(status=200, data=None):
        mock = MagicMock()
        mock.status = status
        if data:
            mock.read.return_value = lambda: str(data).encode()
        return mock

    return _mock


@pytest.fixture
def sample_provider_config():
    """Sample provider configuration for tests."""
    return {
        "claude": {
            "access_token": "test_token",
            "refresh_token": "test_refresh",
            "expires_at": 9999999999999,
        },
        "copilot": {
            "github_token": "gho_test",
            "github_username": "testuser",
            "plan": "pro",
        },
    }


@pytest.fixture
def mock_store():
    """Create a mock Store for testing."""
    with patch("quota_sentinel.store.Store"):
        store = MagicMock()
        store.instances = {}
        store.providers = {}
        store.velocities = {}
        store.effective_poll_interval.return_value = 300
        yield store
