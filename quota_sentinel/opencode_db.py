"""OpenCode SQLite database source for consumption data.

Reads token usage from OpenCode's local SQLite database at:
~/.local/share/opencode/opencode.db

The database schema:
- project: id, worktree, name
- session: id, project_id, provider, started_at
- message: session_id, tokens, role
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

# Maps OpenCode provider identifiers to canonical provider names.
# OpenCode stores provider info as JSON strings in the session.provider column.
PROVIDER_ID_MAP: dict[str, str] = {
    # Zai
    "zai-coding-plan": "zai",
    "zai": "zai",
    # Copilot
    "github-copilot": "copilot",
    "copilot": "copilot",
    # MiniMax
    "minimax-coding-plan": "minimax",
    "minimax": "minimax",
    # DeepSeek
    "deepseek-coding-plan": "deepseek",
    "deepseek": "deepseek",
    # Alibaba
    "bailian-coding-plan": "alibaba",
    "alibaba-coding-plan": "alibaba",
    "dashscope": "alibaba",
    "alibaba": "alibaba",
    # Claude (OAuth)
    "claude": "claude",
    "claude-code": "claude",
    "anthropic": "claude",
}


def _normalize_provider(provider_id: str) -> str:
    """Normalize an OpenCode provider identifier to canonical name."""
    # Try direct match first
    if provider_id in PROVIDER_ID_MAP:
        return PROVIDER_ID_MAP[provider_id]
    # Try case-insensitive match
    lower = provider_id.lower()
    for key, value in PROVIDER_ID_MAP.items():
        if key.lower() == lower:
            return value
    # Unknown provider - return as-is for flexibility
    return provider_id


def _extract_provider_from_json(provider_field: str | None) -> str:
    """Extract provider identifier from JSON string or raw value."""
    if not provider_field:
        return "unknown"
    # Try parsing as JSON first
    try:
        data = json.loads(provider_field)
        if isinstance(data, dict):
            # Look for common provider keys
            for key in ("provider", "name", "type"):
                if key in data:
                    return _normalize_provider(str(data[key]))
        elif isinstance(data, str):
            return _normalize_provider(data)
    except (json.JSONDecodeError, TypeError):
        pass
    # Treat as raw provider identifier
    return _normalize_provider(str(provider_field))


@dataclass
class OpenCodeDBConfig:
    """Configuration for OpenCode database source."""

    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    timeout: float = 2.0  # seconds
    readonly: bool = True


@dataclass
class SessionStats:
    """Aggregated token statistics for a session."""

    session_id: int
    provider: str
    started_at: datetime
    total_tokens: int = 0
    message_count: int = 0
    assistant_tokens: int = 0
    user_tokens: int = 0


@dataclass
class ConsumptionSnapshot:
    """A point-in-time snapshot of token consumption."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    total_tokens: int = 0
    by_provider: dict[str, int] = field(default_factory=dict)
    by_project: dict[str, int] = field(default_factory=dict)
    sessions: list[SessionStats] = field(default_factory=list)


@dataclass
class ProjectUsageSnapshot:
    """Token usage broken down by project and provider."""

    project_path: str
    project_name: str
    providers: dict[str, int] = field(default_factory=dict)  # provider -> tokens
    total_tokens: int = 0
    session_count: int = 0


class OpenCodeDBSource:
    """Reads token consumption data from OpenCode's SQLite database.

    The database is read-only with a short timeout to avoid blocking.
    If the database is unavailable or locked, operations return empty
    results and log a warning.
    """

    def __init__(self, config: OpenCodeDBConfig | None = None):
        self.config = config or OpenCodeDBConfig()

    def _connect(self) -> sqlite3.Connection | None:
        """Establish a read-only connection to the database.

        Returns None if the database is unavailable or locked.
        """
        db_path = self.config.db_path

        if not db_path.exists():
            logger.warning("OpenCode database not found at %s", db_path)
            return None

        try:
            uri = f"file:{db_path}?mode=ro"
            if self.config.readonly:
                uri += "&immutable=1"
            conn = sqlite3.connect(
                uri,
                timeout=self.config.timeout,
                uri=True,
            )
            # Ensure we're in read-only mode by default
            conn.execute("PRAGMA query_only=ON")
            return conn
        except sqlite3.OperationalError as e:
            logger.warning("OpenCode database unavailable: %s", e)
            return None
        except Exception as e:
            logger.warning("Failed to open OpenCode database: %s", e)
            return None

    def get_consumption_snapshot(self) -> ConsumptionSnapshot:
        """Fetch a consumption snapshot aggregating all tokens.

        Returns an empty snapshot if the database cannot be read.
        """
        snapshot = ConsumptionSnapshot()
        conn = self._connect()
        if conn is None:
            return snapshot

        try:
            cursor = conn.execute(
                """
                SELECT
                    s.id AS session_id,
                    s.provider,
                    s.started_at,
                    COALESCE(SUM(m.tokens), 0) AS total_tokens,
                    COUNT(m.id) AS message_count,
                    COALESCE(SUM(CASE WHEN m.role = 'assistant' THEN m.tokens ELSE 0 END), 0) AS assistant_tokens,
                    COALESCE(SUM(CASE WHEN m.role = 'user' THEN m.tokens ELSE 0 END), 0) AS user_tokens
                FROM session s
                LEFT JOIN message m ON m.session_id = s.id
                GROUP BY s.id
                """,
            )

            for row in cursor:
                (
                    session_id,
                    provider_raw,
                    started_at,
                    total_tokens,
                    message_count,
                    assistant_tokens,
                    user_tokens,
                ) = row

                provider = _extract_provider_from_json(provider_raw or "")
                if provider == "unknown":
                    provider = "opencode"  # fallback

                # Parse started_at
                start_time: datetime | None = None
                if started_at:
                    try:
                        start_time = datetime.fromisoformat(started_at)
                    except (ValueError, TypeError):
                        start_time = None

                session = SessionStats(
                    session_id=session_id,
                    provider=provider,
                    started_at=start_time or datetime.now(UTC),
                    total_tokens=total_tokens,
                    message_count=message_count,
                    assistant_tokens=assistant_tokens,
                    user_tokens=user_tokens,
                )
                snapshot.sessions.append(session)
                snapshot.total_tokens += total_tokens
                snapshot.by_provider[provider] = (
                    snapshot.by_provider.get(provider, 0) + total_tokens
                )

            # Now aggregate by project
            cursor = conn.execute(
                """
                SELECT
                    p.worktree,
                    p.name,
                    COALESCE(SUM(m.tokens), 0) AS project_tokens
                FROM project p
                LEFT JOIN session s ON s.project_id = p.id
                LEFT JOIN message m ON m.session_id = s.id
                GROUP BY p.id
                """,
            )

            for row in cursor:
                worktree, name, tokens = row
                project_path = str(worktree) if worktree else ""
                if project_path:
                    snapshot.by_project[project_path] = tokens

        except sqlite3.OperationalError as e:
            logger.warning("Error querying OpenCode database: %s", e)
        except Exception as e:
            logger.warning("Unexpected error reading OpenCode database: %s", e)
        finally:
            conn.close()

        return snapshot

    def get_project_usage(self) -> list[ProjectUsageSnapshot]:
        """Fetch per-project token usage broken down by provider.

        Returns an empty list if the database cannot be read.
        """
        projects: list[ProjectUsageSnapshot] = []
        conn = self._connect()
        if conn is None:
            return projects

        try:
            cursor = conn.execute(
                """
                SELECT
                    p.id AS project_id,
                    p.worktree,
                    p.name,
                    s.provider,
                    COALESCE(SUM(m.tokens), 0) AS tokens,
                    COUNT(DISTINCT s.id) AS session_count
                FROM project p
                LEFT JOIN session s ON s.project_id = p.id
                LEFT JOIN message m ON m.session_id = s.id
                GROUP BY p.id, s.provider
                """,
            )

            # Collect rows by project
            project_data: dict[int, dict[str, Any]] = {}
            for row in cursor:
                (
                    project_id,
                    worktree,
                    name,
                    provider_raw,
                    tokens,
                    session_count,
                ) = row

                provider = _extract_provider_from_json(provider_raw or "")

                if project_id not in project_data:
                    project_data[project_id] = {
                        "worktree": str(worktree) if worktree else "",
                        "name": str(name) if name else "",
                        "providers": {},
                        "total_tokens": 0,
                        "session_count": 0,
                    }

                if provider != "unknown" and tokens > 0:
                    project_data[project_id]["providers"][provider] = (
                        project_data[project_id]["providers"].get(provider, 0) + tokens
                    )
                project_data[project_id]["total_tokens"] += tokens
                project_data[project_id]["session_count"] += session_count

            for project_id, data in project_data.items():
                projects.append(
                    ProjectUsageSnapshot(
                        project_path=data["worktree"],
                        project_name=data["name"] or os.path.basename(data["worktree"]),
                        providers=data["providers"],
                        total_tokens=data["total_tokens"],
                        session_count=data["session_count"],
                    )
                )

        except sqlite3.OperationalError as e:
            logger.warning("Error querying OpenCode database: %s", e)
        except Exception as e:
            logger.warning("Unexpected error reading OpenCode database: %s", e)
        finally:
            conn.close()

        return projects

    def get_session_stats(self, limit: int = 100) -> list[SessionStats]:
        """Fetch recent session statistics.

        Args:
            limit: Maximum number of sessions to return (most recent first).

        Returns an empty list if the database cannot be read.
        """
        sessions: list[SessionStats] = []
        conn = self._connect()
        if conn is None:
            return sessions

        try:
            cursor = conn.execute(
                """
                SELECT
                    s.id AS session_id,
                    s.provider,
                    s.started_at,
                    COALESCE(SUM(m.tokens), 0) AS total_tokens,
                    COUNT(m.id) AS message_count,
                    COALESCE(SUM(CASE WHEN m.role = 'assistant' THEN m.tokens ELSE 0 END), 0) AS assistant_tokens,
                    COALESCE(SUM(CASE WHEN m.role = 'user' THEN m.tokens ELSE 0 END), 0) AS user_tokens
                FROM session s
                LEFT JOIN message m ON m.session_id = s.id
                GROUP BY s.id
                ORDER BY s.started_at DESC
                LIMIT ?
                """,
                (limit,),
            )

            for row in cursor:
                (
                    session_id,
                    provider_raw,
                    started_at,
                    total_tokens,
                    message_count,
                    assistant_tokens,
                    user_tokens,
                ) = row

                provider = _extract_provider_from_json(provider_raw or "")

                start_time: datetime | None = None
                if started_at:
                    try:
                        start_time = datetime.fromisoformat(started_at)
                    except (ValueError, TypeError):
                        start_time = None

                sessions.append(
                    SessionStats(
                        session_id=session_id,
                        provider=provider,
                        started_at=start_time or datetime.now(UTC),
                        total_tokens=total_tokens,
                        message_count=message_count,
                        assistant_tokens=assistant_tokens,
                        user_tokens=user_tokens,
                    )
                )

        except sqlite3.OperationalError as e:
            logger.warning("Error querying OpenCode database: %s", e)
        except Exception as e:
            logger.warning("Unexpected error reading OpenCode database: %s", e)
        finally:
            conn.close()

        return sessions
