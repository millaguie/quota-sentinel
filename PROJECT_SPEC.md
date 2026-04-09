# quota-sentinel — Project Specification

## 1. Overview

**quota-sentinel** is a centralized AI provider quota monitoring daemon. It tracks usage and rate-limit status across multiple AI coding providers (Claude, Copilot, Z.ai, MiniMax, DeepSeek, Alibaba), delivers real-time velocity analysis, exhaustion projections, and per-instance budget allocation. It is designed to be used by AI coding tools like Claude Code and OpenCode to monitor quota availability and make routing decisions.

### 1.1 Platform & Target

- **Platform**: CLI daemon (runs as background service)
- **Language**: python
- **Min version**: Python 3.11+

### 1.2 Key Technologies

| Category | Technology |
|----------|-----------|
| UI       | None (CLI + REST API) |
| Backend  | Starlette + Uvicorn |
| Database | None (in-memory) |
| Testing  | pytest + Docker e2e |
| Build    | Hatchling |
| CI/CD    | GitHub Actions |

---

## 2. Core Features

The core features are already implemented in the codebase:

### 2.1 Multi-Provider Monitoring

Supports multiple AI coding providers:
- Claude (Anthropic OAuth)
- GitHub Copilot
- Z.ai
- MiniMax
- DeepSeek
- Alibaba Cloud

Each provider has a dedicated plugin implementing the UsageProvider ABC.

### 2.2 Velocity Analysis

Linear regression over rolling samples to compute consumption rate (%/hour). Tracks how quickly quota is being consumed to predict future availability.

### 2.3 Exhaustion Projection

Predicts time-to-quota-exhaustion per provider and window. Combines current usage with velocity to estimate when quota will be depleted.

### 2.4 Health Status Engine

Assigns health status to each provider based on utilization, velocity, and configurable safety margins:
- **GREEN**: Safe to use, adequate quota remaining
- **YELLOW**: Caution, quota consumption elevated
- **RED**: Stop or avoid, quota critically low or exhausted

### 2.5 Dynamic Budget Allocation

Divides provider caps across active instances with weighted fairness. The BudgetAllocator distributes available quota among registered instances based on their allocation weights.

### 2.6 Multi-Framework Recommendations

Tailored advice for different AI coding tool workflows:
- **Claude**: Strict stop/proceed recommendations
- **OpenCode**: Fallback-aware recommendations with alternative provider suggestions

### 2.7 Provider Deduplication

Instances sharing the same API key pool into a single polling thread. Uses sha256 fingerprinting to identify duplicate credentials and reduce API calls.

### 2.8 Heartbeat-Based Garbage Collection

Dead instances are automatically reaped after configurable timeout. Instances must send periodic heartbeats to remain active; stale instances are removed to free quota allocation.

---

## 3. Architecture

**Monolithic async daemon with Starlette HTTP server, Click CLI, in-memory state store, and provider plugin architecture.**

### Components

- **CLI Entry Point**: `quota_sentinel.cli` (Click-based)
- **Server**: Starlette application with async lifespan
- **Polling**: asyncio loop running in background task
- **State**: In-memory Store with ProviderEntry and InstanceEntry dataclasses
- **Providers**: Plugin architecture with UsageProvider ABC
- **Engine**: VelocityTracker for rate calculation, `evaluate()` for health status
- **Allocator**: BudgetAllocator for per-instance cap distribution

### Data Flow

1. AI coding tools register with the daemon, providing provider credentials
2. Daemon deduplicates providers by API key fingerprint
3. Background polling loop fetches quota status from each unique provider
4. VelocityTracker computes consumption rate from rolling samples
5. Engine evaluates health status and exhaustion projections
6. BudgetAllocator distributes caps across active instances
7. Tools query the API for recommendations and quota status

---

## 4. Non-Functional Requirements

- **Performance**: Poll interval configurable, default 300s. Provider deduplication reduces API calls to external services.
- **Security**: Auth tokens passed via JSON request bodies (not stored on disk). API key fingerprinting uses sha256 hashing.
- **Operational**: Graceful shutdown via asyncio cancellation. Heartbeat-based garbage collection removes stale instances.

---

## 5. Out of Scope

- Persistence (in-memory only, state is not persisted across restarts)
- User interface beyond REST API and CLI
- Direct integration with AI providers (tools are responsible for API calls)
- Multi-node clustering or distributed state

---

## 6. Open Questions

None currently - implementation is complete.
