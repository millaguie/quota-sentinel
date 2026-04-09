# Quota Sentinel

Centralized AI provider quota monitoring daemon. Tracks usage and rate-limit
status across multiple AI coding providers, delivers real-time velocity analysis,
exhaustion projections, and per-instance budget allocation.

## Features

- **Multi-provider monitoring** -- Claude, GitHub Copilot, Z.ai, MiniMax,
  DeepSeek, and Alibaba Cloud (Tongyi Lingma)
- **Velocity analysis** -- linear regression over rolling samples to compute
  consumption rate (%/hour)
- **Exhaustion projection** -- predicts time-to-quota-exhaustion per provider
  and window
- **Health status engine** -- GREEN / YELLOW / RED based on utilization,
  velocity, and configurable safety margins
- **Dynamic budget allocation** -- divides provider caps across active instances
  with weighted fairness (active > idle > paused) and overcommit support
- **Multi-framework recommendations** -- tailored advice for Claude (strict
  stop/proceed) and OpenCode (fallback-aware) workflows
- **Provider deduplication** -- instances sharing the same API key pool into a
  single polling thread
- **Heartbeat-based GC** -- dead instances are automatically reaped after
  configurable timeout

## Quickstart

### Requirements

- Python 3.11+

### Install

```bash
pip install .
```

### Run

```bash
quota-sentinel start
```

By default the daemon listens on `127.0.0.1:7878`. Override with `--host` /
`--port`:

```bash
quota-sentinel start --host 0.0.0.0 --port 9090
```

### Docker

```bash
docker build -t quota-sentinel .
docker run -p 7878:7878 quota-sentinel
```

## CLI

| Command                  | Description              |
|--------------------------|--------------------------|
| `quota-sentinel start`   | Launch the daemon        |
| `quota-sentinel status`  | Global daemon status     |
| `quota-sentinel health`  | Health check             |

## API

All endpoints live under `/v1`.

### Instance management

| Method   | Path                              | Description                                    |
|----------|-----------------------------------|------------------------------------------------|
| `POST`   | `/v1/instances`                   | Register a client (providers, auth, framework) |
| `DELETE`  | `/v1/instances/{id}`             | Deregister instance                            |
| `PATCH`  | `/v1/instances/{id}/heartbeat`    | Keep-alive with optional state update          |

### Status & monitoring

| Method  | Path                  | Description                                        |
|---------|-----------------------|----------------------------------------------------|
| `GET`   | `/v1/status`          | Global state (all instances, providers, allocations)|
| `GET`   | `/v1/status/{id}`     | Single-instance TOKEN_STATUS with recommendation   |
| `GET`   | `/v1/providers`       | Provider summary (useful for StreamDeck, dashboards)|
| `GET`   | `/v1/providers/{name}`| Detailed provider info with subscriber list        |
| `POST`  | `/v1/poll`            | Trigger immediate repoll                           |
| `GET`   | `/v1/health`          | Server health check                                |

## Providers

| Provider          | Rate-limit windows          | Auth                      |
|-------------------|-----------------------------|---------------------------|
| Claude (Anthropic)| 5-hour, 7-day               | OAuth token               |
| GitHub Copilot    | Monthly                     | GitHub token              |
| Z.ai              | Hours, days, MCP            | API token                 |
| MiniMax           | Per-model, weekly           | API token + group ID      |
| DeepSeek          | Rolling balance             | API token                 |
| Alibaba Cloud     | 5-hour, weekly, monthly     | Session cookie            |

## Configuration

Default hard caps (% utilization before RED):

| Key                 | Default |
|---------------------|---------|
| `claude_five_hour`  | 80%     |
| `claude_seven_day`  | 90%     |
| `copilot_monthly`   | 85%     |
| `zai_default`       | 80%     |
| `minimax_default`   | 85%     |
| `deepseek_default`  | 85%     |
| `alibaba_default`   | 80%     |

Other defaults: poll interval 300s, safety margin 30s, velocity window 10
samples, overcommit factor 1.5x, heartbeat timeout 3x poll interval.

## How it works

1. **Clients register** via `POST /v1/instances` with their providers, auth
   tokens, framework type, and desired poll interval.
2. **Daemon polls** each provider on the fastest registered interval, deduplicating
   by API key fingerprint.
3. **Velocity tracker** maintains a rolling window of (timestamp, utilization)
   samples and computes linear regression slope.
4. **Engine evaluates** each provider-window pair: compares utilization against
   dynamic threshold, projects minutes-to-exhaustion, and assigns health status.
5. **Allocator divides** the hard cap budget across subscribed instances weighted
   by state (active 1.0, idle 0.3, paused 0.0) with configurable overcommit.
6. **Clients query** `GET /v1/status/{id}` for a recommendation
   (`PROCEED` / `PROCEED_SMALL_ONLY` / `STOP`) tailored to their framework.

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html).
