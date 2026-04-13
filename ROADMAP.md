# quota-sentinel Roadmap

## Phase 1: Test Infrastructure (Setup)

### P1-T01: Set up pytest configuration
- **Description**: Configure pytest, add conftest.py, set up test discovery
- **Status**: DONE
- **Size**: S

### P1-T02: Create tests directory structure
- **Description**: Create tests/ directory with __init__.py, conftest.py
- **Status**: DONE
- **Size**: S

### P1-T03: Write unit tests for engine.py (VelocityTracker)
- **Description**: Test velocity calculation, exhaustion projection, linear regression
- **Status**: DONE
- **Size**: M

### P1-T04: Write unit tests for allocator.py
- **Description**: Test budget allocation logic, weight calculation
- **Status**: DONE
- **Size**: M

### P1-T05: Write unit tests for store.py
- **Description**: Test instance registration, heartbeat, GC logic
- **Status**: DONE
- **Size**: M

### P1-T06: Create Dockerfile.e2e for end-to-end tests
- **Description**: Create Dockerfile.e2e that builds image and runs e2e client simulation
- **Status**: DONE
- **Size**: M

### P1-T07: Write e2e tests (Docker-based)
- **Description**: Write tests that start container, register instance, verify API responses
- **Status**: DONE
- **Size**: L

### P1-T08: Verify CI passes with tests
- **Description**: Update CI workflow to actually run pytest, verify all pass
- **Status**: DONE
- **Size**: S

---

## Phase 2: Quality & Coverage

### P2-T01: Increase test coverage to 80%
- **Description**: Identify gaps, add tests for uncovered paths
- **Status**: DONE
- **Size**: L

### P2-T02: Fix mypy type errors
- **Description**: Fix pre-existing type errors in server.py and daemon.py
- **Status**: DONE
- **Size**: M

### P2-T03: Add provider tests (mocked HTTP)
- **Description**: Test provider fetch methods with mocked HTTP responses
- **Status**: TODO
- **Size**: L

---

## Phase 3: Features & Improvements

### P3-T01: Add configuration via environment variables
- **Description**: Support HOST, PORT, POLL_INTERVAL env vars
- **Status**: DONE
- **Size**: S

### P3-T02: Add metrics endpoint
- **Description**: Add /v1/metrics for Prometheus-compatible metrics
- **Status**: DONE
- **Size**: M

### P3-T03: Improve error handling in providers
- **Description**: Better error messages, retry logic
- **Status**: DONE
- **Size**: M

---

## Phase 4: OpenCode DB Integration

OpenCode stores real consumption data per project/provider/model in `~/.local/share/opencode/opencode.db`. This phase integrates that data to provide token-based session forecasting, calibrate tokens-per-percentage for providers that don't report absolutes, and add newly discovered providers.

### P4-T01: Create OpenCodeDBSource (DB reader)
- **Description**: New module `quota_sentinel/opencode_db.py` — dataclasses (`OpenCodeDBConfig`, `ConsumptionSnapshot`, `SessionStats`, `ProjectUsageSnapshot`) and `OpenCodeDBSource` class. Reads OpenCode DB read-only (`?mode=ro`, 2s timeout). SQL queries with `json_extract` aggregating tokens by project (`p.worktree`) and provider. Extended provider ID mapping. Graceful when DB unavailable/locked.
- **Status**: DONE
- **Size**: L

### P4-T02: Tests for OpenCodeDBSource
- **Description**: Unit tests with in-memory SQLite replicating OpenCode schema (project, session, message). Synthetic data with known tokens. Tests: token aggregation, avg_tokens_per_session calculation, provider mapping, DB unavailable returns empty, null fields, error_rate, multi-provider sessions.
- **Status**: DONE
- **Size**: M

### P4-T03: Integrate config and storage
- **Description**: Add `OpenCodeDBConfig` to `ServerConfig`. Add storage fields to `Store` (`opencode_consumption`, `opencode_projects`, `opencode_session_stats`, `opencode_last_poll`) and `update_opencode_data()` method. CLI flags: `--enable-opencode-db`, `--opencode-db PATH`, `--opencode-poll-interval`.
- **Status**: DONE
- **Size**: M

### P4-T04: Integrate polling in daemon loop
- **Description**: In `daemon.py`, if `config.opencode_db.enabled`, create `OpenCodeDBSource` and poll in executor with independent timer (default 120s). Correlate instance `project_name` with OpenCode `worktree`. Log warning and continue if DB unavailable.
- **Status**: DONE
- **Size**: M

### P4-T05: Token-per-percentage calibration
- **Description**: Calibrate how many tokens = 1% of each provider/window quota. Between two polls, cross-reference: (a) utilization% delta from provider API, (b) tokens consumed from OpenCode DB. Store calibration per provider/window. Use moving average of last N calibrations to smooth noise. Enables converting utilization% to absolute tokens for providers that don't report token counts.
- **Status**: DONE
- **Size**: L

### P4-T06: Sessions remaining calculation
- **Description**: Implement `estimated_sessions_remaining`: remaining tokens (calibrated via P4-T05) / avg_tokens_per_session (from OpenCode DB). Configurable threshold (default 1.5) — if `sessions_remaining < threshold`, recommend provider switch BEFORE starting new session. Integrate in `build_instance_status()` and enrich `evaluate()` to treat low sessions_remaining as YELLOW/RED.
- **Status**: DONE
- **Size**: L

### P4-T07: Project and consumption endpoints
- **Description**: New endpoints: `GET /v1/projects` (project list with total_tokens, requests, providers, avg_tokens_per_session, sessions_remaining), `GET /v1/projects/{name}` (detail by provider/model), `GET /v1/consumption` (global consumption by provider with tokens, error_rate, latency). Extend `GET /v1/status/{id}` with project token usage and sessions_remaining. Extend `GET /v1/status` with `opencode_source` metadata.
- **Status**: DONE
- **Size**: L

### P4-T08: New providers (cerebras, openai, opencode)
- **Description**: Implement providers discovered in OpenCode DB (not ollama — local, no quota): `CerebrasUsageProvider`, `OpenAIUsageProvider`, `OpenCodeUsageProvider` (for free models like minimax-m2.5-free, qwen3.6-plus-free). Add to `create_provider()` factory, `AUTH_KEY_TO_PROVIDER`, and default hard caps.
- **Status**: DONE
- **Size**: L

---

## Notes

- All tasks in Phase 1 must complete before Phase 2
- Phase 4 depends on Phase 1 (test infra) but can run in parallel with Phases 2-3
- P4-T05 and P4-T06 depend on P4-T01 through P4-T04
- P4-T08 is independent and can be done in any order
- Ralph will execute tasks in order
- Each task should be PR-sized (one small commit per task)
