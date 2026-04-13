"""Unit tests for quota_sentinel.opencode_db module."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


from quota_sentinel.opencode_db import (
    PROVIDER_ID_MAP,
    OpenCodeDBConfig,
    OpenCodeDBSource,
    ProjectUsageSnapshot,
    SessionStats,
    ConsumptionSnapshot,
    _extract_provider_from_json,
    _normalize_provider,
)


# =============================================================================
# Helper Functions Tests
# =============================================================================


class TestNormalizeProvider:
    """Tests for _normalize_provider() function."""

    def test_zai_provider(self):
        """Maps zai provider identifiers correctly."""
        assert _normalize_provider("zai-coding-plan") == "zai"
        assert _normalize_provider("zai") == "zai"

    def test_copilot_provider(self):
        """Maps copilot provider identifiers correctly."""
        assert _normalize_provider("github-copilot") == "copilot"
        assert _normalize_provider("copilot") == "copilot"

    def test_minimax_provider(self):
        """Maps minimax provider identifiers correctly."""
        assert _normalize_provider("minimax-coding-plan") == "minimax"
        assert _normalize_provider("minimax") == "minimax"

    def test_deepseek_provider(self):
        """Maps deepseek provider identifiers correctly."""
        assert _normalize_provider("deepseek-coding-plan") == "deepseek"
        assert _normalize_provider("deepseek") == "deepseek"

    def test_alibaba_provider(self):
        """Maps alibaba provider identifiers correctly."""
        assert _normalize_provider("bailian-coding-plan") == "alibaba"
        assert _normalize_provider("alibaba-coding-plan") == "alibaba"
        assert _normalize_provider("dashscope") == "alibaba"
        assert _normalize_provider("alibaba") == "alibaba"

    def test_claude_provider(self):
        """Maps claude provider identifiers correctly."""
        assert _normalize_provider("claude") == "claude"
        assert _normalize_provider("claude-code") == "claude"
        assert _normalize_provider("anthropic") == "claude"

    def test_unknown_provider(self):
        """Unknown provider identifiers are returned as-is."""
        assert _normalize_provider("unknown-provider") == "unknown-provider"

    def test_provider_id_map_contains_all_expected_keys(self):
        """Provider ID map contains expected provider types."""
        expected_providers = {
            "zai",
            "copilot",
            "minimax",
            "deepseek",
            "alibaba",
            "claude",
        }
        mapped_values = set(PROVIDER_ID_MAP.values())
        assert expected_providers.issubset(mapped_values)


class TestExtractProviderFromJson:
    """Tests for _extract_provider_from_json() function."""

    def test_raw_provider_string(self):
        """Extracts provider from raw string value."""
        assert _extract_provider_from_json("claude") == "claude"
        assert _extract_provider_from_json("zai-coding-plan") == "zai"

    def test_json_with_provider_key(self):
        """Extracts provider from JSON object with 'provider' key."""
        json_str = json.dumps({"provider": "claude", "key": "value"})
        assert _extract_provider_from_json(json_str) == "claude"

    def test_json_with_name_key(self):
        """Extracts provider from JSON object with 'name' key."""
        json_str = json.dumps({"name": "deepseek", "other": "data"})
        assert _extract_provider_from_json(json_str) == "deepseek"

    def test_json_with_type_key(self):
        """Extracts provider from JSON object with 'type' key."""
        json_str = json.dumps({"type": "minimax"})
        assert _extract_provider_from_json(json_str) == "minimax"

    def test_json_with_string_value(self):
        """Extracts provider when JSON is just a string."""
        json_str = json.dumps("minimax")
        assert _extract_provider_from_json(json_str) == "minimax"

    def test_empty_string(self):
        """Returns 'unknown' for empty string."""
        assert _extract_provider_from_json("") == "unknown"

    def test_none_provider(self):
        """Returns 'unknown' for None."""
        assert _extract_provider_from_json(None) == "unknown"

    def test_invalid_json_falls_back_to_raw(self):
        """Invalid JSON is treated as raw provider string."""
        assert _extract_provider_from_json("not-valid-json") == "not-valid-json"


# =============================================================================
# OpenCodeDBConfig Tests
# =============================================================================


class TestOpenCodeDBConfig:
    """Tests for OpenCodeDBConfig dataclass."""

    def test_default_values(self):
        """Default configuration uses expected paths and settings."""
        config = OpenCodeDBConfig()
        assert (
            config.db_path
            == Path.home() / ".local" / "share" / "opencode" / "opencode.db"
        )
        assert config.timeout == 2.0
        assert config.readonly is True

    def test_custom_values(self):
        """Custom configuration overrides defaults."""
        custom_path = Path("/custom/path/db")
        config = OpenCodeDBConfig(db_path=custom_path, timeout=5.0, readonly=False)
        assert config.db_path == custom_path
        assert config.timeout == 5.0
        assert config.readonly is False


# =============================================================================
# OpenCodeDBSource Tests
# =============================================================================


class TestOpenCodeDBSourceInitialization:
    """Tests for OpenCodeDBSource initialization."""

    def test_default_initialization(self):
        """Creates source with default config."""
        source = OpenCodeDBSource()
        assert source.config.timeout == 2.0
        assert source.config.readonly is True

    def test_custom_config_initialization(self):
        """Creates source with custom config."""
        config = OpenCodeDBConfig(timeout=5.0)
        source = OpenCodeDBSource(config)
        assert source.config.timeout == 5.0


class TestOpenCodeDBSourceConnect:
    """Tests for OpenCodeDBSource._connect() method."""

    def test_returns_none_when_db_not_found(self, tmp_path):
        """Returns None when database path doesn't exist."""
        config = OpenCodeDBConfig(db_path=tmp_path / "nonexistent.db")
        source = OpenCodeDBSource(config)
        result = source._connect()
        assert result is None

    def test_returns_connection_when_db_exists(self, tmp_path):
        """Returns connection when database exists."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)
        result = source._connect()
        assert result is not None
        result.close()


class TestOpenCodeDBSourceConsumptionSnapshot:
    """Tests for OpenCodeDBSource.get_consumption_snapshot() method."""

    def _create_test_db(self, tmp_path: Path) -> Path:
        """Create a test database with sample data."""
        db_path = tmp_path / "test_opencode.db"
        conn = sqlite3.connect(str(db_path))

        # Create tables
        conn.execute("""
            CREATE TABLE project (
                id INTEGER PRIMARY KEY,
                worktree TEXT,
                name TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE session (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                provider TEXT,
                started_at TEXT,
                FOREIGN KEY (project_id) REFERENCES project(id)
            )
        """)
        conn.execute("""
            CREATE TABLE message (
                id INTEGER PRIMARY KEY,
                session_id INTEGER,
                tokens INTEGER,
                role TEXT,
                FOREIGN KEY (session_id) REFERENCES session(id)
            )
        """)

        # Insert test data
        conn.execute(
            "INSERT INTO project (id, worktree, name) VALUES (1, '/home/user/project1', 'Project 1')"
        )
        conn.execute(
            "INSERT INTO project (id, worktree, name) VALUES (2, '/home/user/project2', 'Project 2')"
        )
        conn.execute(
            "INSERT INTO project (id, worktree, name) VALUES (3, '/home/user/project3', 'Project 3')"
        )

        # Sessions with JSON provider strings
        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (1, 1, '{\"provider\": \"claude\"}', '2024-01-01T10:00:00')"
        )
        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (2, 1, '{\"provider\": \"zai-coding-plan\"}', '2024-01-01T11:00:00')"
        )
        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (3, 2, 'copilot', '2024-01-01T12:00:00')"
        )
        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (4, 3, 'minimax', '2024-01-01T13:00:00')"
        )

        # Messages
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (1, 1000, 'user')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (1, 2000, 'assistant')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (1, 500, 'user')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (2, 3000, 'user')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (2, 4000, 'assistant')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (3, 1500, 'user')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (3, 2500, 'assistant')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (4, 5000, 'user')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (4, 6000, 'assistant')"
        )

        conn.commit()
        conn.close()
        return db_path

    def test_returns_empty_snapshot_when_db_missing(self, tmp_path):
        """Returns empty snapshot when database doesn't exist."""
        config = OpenCodeDBConfig(db_path=tmp_path / "nonexistent.db")
        source = OpenCodeDBSource(config)
        snapshot = source.get_consumption_snapshot()

        assert snapshot.total_tokens == 0
        assert snapshot.by_provider == {}
        assert snapshot.by_project == {}
        assert snapshot.sessions == []

    def test_consumption_snapshot_aggregates_tokens(self, tmp_path):
        """Snapshot correctly aggregates tokens from all sessions."""
        db_path = self._create_test_db(tmp_path)
        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)

        snapshot = source.get_consumption_snapshot()

        # Total: 1000+2000+500 + 3000+4000 + 1500+2500 + 5000+6000 = 25500
        assert snapshot.total_tokens == 25500

    def test_consumption_snapshot_by_provider(self, tmp_path):
        """Snapshot correctly groups tokens by provider."""
        db_path = self._create_test_db(tmp_path)
        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)

        snapshot = source.get_consumption_snapshot()

        # claude: 1000+2000+500 = 3500
        # zai: 3000+4000 = 7000
        # copilot: 1500+2500 = 4000
        # minimax: 5000+6000 = 11000
        assert snapshot.by_provider["claude"] == 3500
        assert snapshot.by_provider["zai"] == 7000
        assert snapshot.by_provider["copilot"] == 4000
        assert snapshot.by_provider["minimax"] == 11000

    def test_consumption_snapshot_by_project(self, tmp_path):
        """Snapshot correctly groups tokens by project."""
        db_path = self._create_test_db(tmp_path)
        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)

        snapshot = source.get_consumption_snapshot()

        # project1 (sessions 1,2): 3500+7000 = 10500
        # project2 (session 3): 4000
        # project3 (session 4): 11000
        assert snapshot.by_project["/home/user/project1"] == 10500
        assert snapshot.by_project["/home/user/project2"] == 4000
        assert snapshot.by_project["/home/user/project3"] == 11000

    def test_consumption_snapshot_sessions_detail(self, tmp_path):
        """Snapshot contains detailed session information."""
        db_path = self._create_test_db(tmp_path)
        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)

        snapshot = source.get_consumption_snapshot()

        assert len(snapshot.sessions) == 4

        # Session 1 - claude
        session1 = next(s for s in snapshot.sessions if s.session_id == 1)
        assert session1.provider == "claude"
        assert session1.total_tokens == 3500
        assert session1.message_count == 3
        assert session1.assistant_tokens == 2000
        assert session1.user_tokens == 1500

        # Session 2 - zai
        session2 = next(s for s in snapshot.sessions if s.session_id == 2)
        assert session2.provider == "zai"
        assert session2.total_tokens == 7000

        # Session 3 - copilot
        session3 = next(s for s in snapshot.sessions if s.session_id == 3)
        assert session3.provider == "copilot"
        assert session3.total_tokens == 4000

        # Session 4 - minimax
        session4 = next(s for s in snapshot.sessions if s.session_id == 4)
        assert session4.provider == "minimax"
        assert session4.total_tokens == 11000


class TestOpenCodeDBSourceProjectUsage:
    """Tests for OpenCodeDBSource.get_project_usage() method."""

    def _create_test_db(self, tmp_path: Path) -> Path:
        """Create a test database with sample data."""
        db_path = tmp_path / "test_opencode.db"
        conn = sqlite3.connect(str(db_path))

        conn.execute("""
            CREATE TABLE project (
                id INTEGER PRIMARY KEY,
                worktree TEXT,
                name TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE session (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                provider TEXT,
                started_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE message (
                id INTEGER PRIMARY KEY,
                session_id INTEGER,
                tokens INTEGER,
                role TEXT
            )
        """)

        conn.execute(
            "INSERT INTO project (id, worktree, name) VALUES (1, '/home/user/project1', 'Project 1')"
        )
        conn.execute(
            "INSERT INTO project (id, worktree, name) VALUES (2, '/home/user/project2', 'Project 2')"
        )

        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (1, 1, '{\"provider\": \"claude\"}', '2024-01-01T10:00:00')"
        )
        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (2, 1, '{\"provider\": \"zai\"}', '2024-01-01T11:00:00')"
        )
        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (3, 2, 'copilot', '2024-01-01T12:00:00')"
        )

        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (1, 1000, 'user')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (1, 2000, 'assistant')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (2, 3000, 'assistant')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (3, 1500, 'user')"
        )

        conn.commit()
        conn.close()
        return db_path

    def test_returns_empty_list_when_db_missing(self, tmp_path):
        """Returns empty list when database doesn't exist."""
        config = OpenCodeDBConfig(db_path=tmp_path / "nonexistent.db")
        source = OpenCodeDBSource(config)
        result = source.get_project_usage()

        assert result == []

    def test_project_usage_correctly_aggregated(self, tmp_path):
        """Project usage correctly aggregates by project and provider."""
        db_path = self._create_test_db(tmp_path)
        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)

        projects = source.get_project_usage()

        assert len(projects) == 2

        project1 = next(p for p in projects if p.project_path == "/home/user/project1")
        assert project1.project_name == "Project 1"
        assert project1.providers["claude"] == 3000
        assert project1.providers["zai"] == 3000
        assert project1.total_tokens == 6000
        assert project1.session_count == 2

        project2 = next(p for p in projects if p.project_path == "/home/user/project2")
        assert project2.project_name == "Project 2"
        assert project2.providers["copilot"] == 1500
        assert project2.total_tokens == 1500
        assert project2.session_count == 1


class TestOpenCodeDBSourceSessionStats:
    """Tests for OpenCodeDBSource.get_session_stats() method."""

    def _create_test_db(self, tmp_path: Path) -> Path:
        """Create a test database with sample data."""
        db_path = tmp_path / "test_opencode.db"
        conn = sqlite3.connect(str(db_path))

        conn.execute("""
            CREATE TABLE session (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                provider TEXT,
                started_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE message (
                id INTEGER PRIMARY KEY,
                session_id INTEGER,
                tokens INTEGER,
                role TEXT
            )
        """)

        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (1, 1, 'claude', '2024-01-01T10:00:00')"
        )
        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (2, 1, 'zai', '2024-01-01T11:00:00')"
        )
        conn.execute(
            "INSERT INTO session (id, project_id, provider, started_at) VALUES (3, 1, 'copilot', '2024-01-01T12:00:00')"
        )

        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (1, 1000, 'user')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (1, 2000, 'assistant')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (2, 3000, 'assistant')"
        )
        conn.execute(
            "INSERT INTO message (session_id, tokens, role) VALUES (3, 1500, 'user')"
        )

        conn.commit()
        conn.close()
        return db_path

    def test_returns_empty_list_when_db_missing(self, tmp_path):
        """Returns empty list when database doesn't exist."""
        config = OpenCodeDBConfig(db_path=tmp_path / "nonexistent.db")
        source = OpenCodeDBSource(config)
        result = source.get_session_stats()

        assert result == []

    def test_session_stats_respects_limit(self, tmp_path):
        """Session stats returns only the specified number of sessions."""
        db_path = self._create_test_db(tmp_path)
        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)

        sessions = source.get_session_stats(limit=2)

        assert len(sessions) == 2

    def test_session_stats_ordered_by_started_at_desc(self, tmp_path):
        """Session stats returns sessions ordered by most recent first."""
        db_path = self._create_test_db(tmp_path)
        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)

        sessions = source.get_session_stats(limit=10)

        # Session 3 (12:00) is most recent, then 2 (11:00), then 1 (10:00)
        assert sessions[0].session_id == 3
        assert sessions[1].session_id == 2
        assert sessions[2].session_id == 1

    def test_session_stats_calculates_tokens_correctly(self, tmp_path):
        """Session stats correctly calculates token totals."""
        db_path = self._create_test_db(tmp_path)
        config = OpenCodeDBConfig(db_path=db_path)
        source = OpenCodeDBSource(config)

        sessions = source.get_session_stats(limit=10)

        session1 = next(s for s in sessions if s.session_id == 1)
        assert session1.total_tokens == 3000
        assert session1.message_count == 2
        assert session1.assistant_tokens == 2000
        assert session1.user_tokens == 1000


class TestDataclasses:
    """Tests for the dataclasses used by OpenCodeDBSource."""

    def test_session_stats_defaults(self):
        """SessionStats has correct default values."""
        stats = SessionStats(
            session_id=1,
            provider="claude",
            started_at=datetime.now(UTC),
        )
        assert stats.total_tokens == 0
        assert stats.message_count == 0
        assert stats.assistant_tokens == 0
        assert stats.user_tokens == 0

    def test_consumption_snapshot_defaults(self):
        """ConsumptionSnapshot has correct default values."""
        snapshot = ConsumptionSnapshot()
        assert snapshot.total_tokens == 0
        assert snapshot.by_provider == {}
        assert snapshot.by_project == {}
        assert snapshot.sessions == []

    def test_project_usage_snapshot_defaults(self):
        """ProjectUsageSnapshot has correct default values."""
        usage = ProjectUsageSnapshot(
            project_path="/home/user/project",
            project_name="My Project",
        )
        assert usage.providers == {}
        assert usage.total_tokens == 0
        assert usage.session_count == 0
