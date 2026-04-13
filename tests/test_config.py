"""Unit tests for quota_sentinel.config module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from quota_sentinel.config import ServerConfig
from quota_sentinel.opencode_db import OpenCodeDBConfig


class TestServerConfigFromEnv:
    """Tests for ServerConfig.from_env() class method."""

    def test_from_env_with_no_env_vars_uses_defaults(self):
        """When no env vars are set, from_env returns defaults."""
        env = {}
        with patch.dict(os.environ, env, clear=True):
            config = ServerConfig.from_env()

        assert config.host == "127.0.0.1"
        assert config.port == 7878
        assert config.default_poll_interval == 300

    def test_from_env_reads_host_from_env(self):
        """HOST env var overrides the host default."""
        with patch.dict(os.environ, {"HOST": "0.0.0.0"}, clear=True):
            config = ServerConfig.from_env()

        assert config.host == "0.0.0.0"

    def test_from_env_reads_port_from_env(self):
        """PORT env var overrides the port default."""
        with patch.dict(os.environ, {"PORT": "9000"}, clear=True):
            config = ServerConfig.from_env()

        assert config.port == 9000

    def test_from_env_reads_poll_interval_from_env(self):
        """POLL_INTERVAL env var overrides the poll interval default."""
        with patch.dict(os.environ, {"POLL_INTERVAL": "600"}, clear=True):
            config = ServerConfig.from_env()

        assert config.default_poll_interval == 600

    def test_from_env_reads_all_env_vars(self):
        """All env vars are read correctly when set."""
        with patch.dict(
            os.environ,
            {"HOST": "192.168.1.1", "PORT": "8080", "POLL_INTERVAL": "120"},
            clear=True,
        ):
            config = ServerConfig.from_env()

        assert config.host == "192.168.1.1"
        assert config.port == 8080
        assert config.default_poll_interval == 120


class TestServerConfigEnvOverride:
    """Tests that ServerConfig properly handles environment variable overrides."""

    def test_explicit_host_overrides_env(self):
        """Explicit host argument overrides HOST env var."""
        with patch.dict(os.environ, {"HOST": "0.0.0.0"}, clear=True):
            config = ServerConfig(host="127.0.0.1")

        assert config.host == "127.0.0.1"

    def test_explicit_port_overrides_env(self):
        """Explicit port argument overrides PORT env var."""
        with patch.dict(os.environ, {"PORT": "9000"}, clear=True):
            config = ServerConfig(port=8080)

        assert config.port == 8080

    def test_explicit_poll_interval_overrides_env(self):
        """Explicit poll_interval argument overrides POLL_INTERVAL env var."""
        with patch.dict(os.environ, {"POLL_INTERVAL": "600"}, clear=True):
            config = ServerConfig(default_poll_interval=300)

        assert config.default_poll_interval == 300


class TestServerConfigDefaults:
    """Tests for ServerConfig default values."""

    def test_default_host(self):
        """Default host is 127.0.0.1."""
        config = ServerConfig()
        assert config.host == "127.0.0.1"

    def test_default_port(self):
        """Default port is 7878."""
        config = ServerConfig()
        assert config.port == 7878

    def test_default_poll_interval(self):
        """Default poll interval is 300."""
        config = ServerConfig()
        assert config.default_poll_interval == 300

    def test_default_safety_margin_min(self):
        """Default safety margin is 30 seconds."""
        config = ServerConfig()
        assert config.safety_margin_min == 30

    def test_default_velocity_window(self):
        """Default velocity window is 10."""
        config = ServerConfig()
        assert config.velocity_window == 10

    def test_default_overcommit_factor(self):
        """Default overcommit factor is 1.5."""
        config = ServerConfig()
        assert config.overcommit_factor == 1.5

    def test_default_heartbeat_timeout_factor(self):
        """Default heartbeat timeout factor is 3.0."""
        config = ServerConfig()
        assert config.heartbeat_timeout_factor == 3.0

    def test_default_hard_caps(self):
        """Default hard caps include all providers."""
        from quota_sentinel.config import DEFAULT_HARD_CAPS

        config = ServerConfig()
        assert config.hard_caps == DEFAULT_HARD_CAPS

    def test_default_enable_opencode_db(self):
        """Default enable_opencode_db is False."""
        config = ServerConfig()
        assert config.enable_opencode_db is False

    def test_default_opencode_db_path(self):
        """Default opencode_db_path is None."""
        config = ServerConfig()
        assert config.opencode_db_path is None

    def test_default_opencode_poll_interval(self):
        """Default opencode_poll_interval is 60 seconds."""
        config = ServerConfig()
        assert config.opencode_poll_interval == 60

    def test_default_opencode_db_config(self):
        """Default opencode_db is None."""
        config = ServerConfig()
        assert config.opencode_db is None

    def test_enable_opencode_db_can_be_set(self):
        """enable_opencode_db can be set explicitly."""
        config = ServerConfig(enable_opencode_db=True)
        assert config.enable_opencode_db is True

    def test_opencode_db_path_can_be_set(self):
        """opencode_db_path can be set to a Path."""
        path = Path("/custom/path/opencode.db")
        config = ServerConfig(opencode_db_path=path)
        assert config.opencode_db_path == path

    def test_opencode_poll_interval_can_be_set(self):
        """opencode_poll_interval can be set explicitly."""
        config = ServerConfig(opencode_poll_interval=120)
        assert config.opencode_poll_interval == 120

    def test_opencode_db_is_built_from_enable_and_path(self):
        """When enable_opencode_db=True, opencode_db is a OpenCodeDBConfig."""
        path = Path("/test/opencode.db")
        config = ServerConfig(enable_opencode_db=True, opencode_db_path=path)
        assert config.opencode_db is not None
        assert isinstance(config.opencode_db, OpenCodeDBConfig)
        assert config.opencode_db.db_path == path

    def test_opencode_db_stays_none_when_disabled(self):
        """When enable_opencode_db=False, opencode_db is None even if path set."""
        config = ServerConfig(
            enable_opencode_db=False, opencode_db_path=Path("/test.db")
        )
        assert config.opencode_db is None
