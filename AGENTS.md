# quota-sentinel — Agent Configuration

## Project Context

**quota-sentinel** is a centralized AI provider quota monitoring daemon built in Python. It monitors quota usage across multiple AI providers (Claude, Copilot, Z.ai, MiniMax, DeepSeek, Alibaba) and provides a REST API for status and recommendations.

## Agent Team

| Agent | Role | Focus Areas |
|-------|------|--------------|
| build | Development | Write code, run tests, build project |
| plan | Architecture | Analyze codebase, design solutions, maintain ROADMAP |
| ralph | Autonomous loop | Pick ROADMAP tasks, delegate to subagents, commit, loop |
| pm | Project manager | Maintain ROADMAP, deliver builds, bug tracking |
| reviewer | Code review | Quality, correctness, best practices |
| explorer | Codebase exploration | Find patterns, search code, map architecture |
| test | Testing | Write tests, validate coverage, quality gates |
| sre | SRE/Debugging | Diagnose live issues, analyze logs |
| security | Security audit | Code, config, dependencies |
| docs | Documentation | READMEs, API references |
| refactor | Refactoring | Improve code structure, reduce duplication |
| devops | DevOps/Infra | CI/CD, Dockerfiles, deployment |

## Build Commands (for build agent)

```bash
# Activate virtual environment FIRST
source .venv/bin/activate

# Install package in editable mode with dev dependencies
pip install -e ".[dev]"

# Run linter
ruff check .

# Run formatter check
ruff format --check .

# Run type checker
mypy quota_sentinel/

# Run unit tests
pytest

# Run e2e tests (requires Docker)
docker build -t quota-sentinel-test -f Dockerfile.e2e .
docker run --rm quota-sentinel-test

# Build the project
pip install -e .

# Build Docker image
docker build -t quota-sentinel .
```

## Test Commands (for test agent)

```bash
# Unit tests
pytest

# With coverage
pytest --cov=quota_sentinel --cov-report=term-missing

# E2E tests via Docker
docker build -t quota-sentinel-test -f Dockerfile.e2e .
docker run --rm quota-sentinel-test

# Test a specific module
pytest tests/test_engine.py -v
```

## Reviewer Focus Areas

- API handlers in `server.py` — request parsing, response formatting
- Provider implementations — API calls, error handling
- Async patterns — daemon loop, lifespan management
- Auth token handling — security implications
- Velocity calculation in `engine.py` — correctness of linear regression

## Security Focus Areas

- Auth tokens passed via JSON (not stored on disk) ✓
- API key fingerprinting (sha256) ✓
- No secrets in codebase
- OAuth token refresh for Claude

## Key Files

| File | Purpose |
|------|---------|
| `quota_sentinel/cli.py` | Click CLI entry point |
| `quota_sentinel/server.py` | Starlette HTTP server with REST API |
| `quota_sentinel/daemon.py` | Async polling loop |
| `quota_sentinel/store.py` | In-memory state (instances, providers) |
| `quota_sentinel/engine.py` | Velocity tracking, health evaluation |
| `quota_sentinel/allocator.py` | Budget allocation across instances |
| `quota_sentinel/config.py` | ServerConfig + default hard caps |
| `quota_sentinel/providers/` | Provider implementations |

## Code Conventions

- Use type hints throughout (Python 3.11+ style with `|` unions)
- Use dataclasses for DTOs
- Use `from __future__ import annotations` at the top of every file
- Use module-level loggers: `logger = logging.getLogger(__name__)`
- All async handlers in server.py use the module-level `_store` and `_config` globals set during lifespan
