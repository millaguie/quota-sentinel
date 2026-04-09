# quota-sentinel

## Project Overview

**quota-sentinel** is a centralized AI provider quota monitoring daemon. It tracks usage and rate-limit status across multiple AI coding providers (Claude, Copilot, Z.ai, MiniMax, DeepSeek, Alibaba Cloud), delivers real-time velocity analysis, exhaustion projections, and per-instance budget allocation.

## Agent Workflow

This project uses the following agents:

- **build**: Development agent - writes code, runs tests, builds the project
- **plan**: Architecture and planning agent - analyzes codebase, designs solutions, maintains ROADMAP
- **ralph**: Autonomous loop coordinator - picks ROADMAP tasks, delegates to subagents, commits, loops
- **pm**: Project manager - maintains ROADMAP, delivers builds, manages priorities, bug tracking, and agent team
- **reviewer**: Code reviewer - checks code quality, correctness, and best practices
- **explorer**: Codebase explorer - finds patterns, searches code, maps architecture
- **test**: Test specialist - writes tests, validates coverage, enforces quality gates
- **sre**: SRE/debugger - diagnoses live system issues, analyzes logs, traces errors in running environments
- **security**: Security auditor - reviews code, config, dependencies for vulnerabilities
- **docs**: Documentation agent - generates and maintains docs, READMEs, API references, decision records
- **refactor**: Refactoring specialist - improves code structure, reduces duplication, maintains behavior
- **devops**: DevOps/infra agent - manages CI/CD, Dockerfiles, deployment configs, infrastructure


## Security

- Security profile: **moderate**
- Never commit secrets or API keys
- Set credentials via environment variables
- Auth tokens passed via JSON body (not stored on disk)


## Development Commands

```bash
# Activate virtual environment FIRST
source .venv/bin/activate

# Install package in editable mode
pip install -e .

# Install dev dependencies (pytest, etc.)
pip install pytest pytest-asyncio httpx

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

# Run the daemon locally
quota-sentinel start --host 127.0.0.1 --port 7878

# Run with custom poll interval
quota-sentinel start --poll-interval 60
```

## Key Files

- `quota_sentinel/cli.py` - Click CLI entry point
- `quota_sentinel/server.py` - Starlette HTTP server with REST API
- `quota_sentinel/daemon.py` - Async polling loop
- `quota_sentinel/store.py` - In-memory state (instances, providers)
- `quota_sentinel/engine.py` - Velocity tracking, health evaluation
- `quota_sentinel/allocator.py` - Budget allocation across instances
- `quota_sentinel/config.py` - ServerConfig + default hard caps
- `quota_sentinel/providers/` - Provider implementations (base, claude, copilot, zai, minimax, deepseek, alibaba)

## Code Conventions

- Use type hints throughout (Python 3.11+ style with `|` unions)
- Use dataclasses for DTOs
- Use `from __future__ import annotations` at the top of every file
- Use module-level loggers: `logger = logging.getLogger(__name__)`
- Use `logging.getLogger(__name__)` pattern for all modules
- All async handlers in server.py use the module-level `_store` and `_config` globals set during lifespan
