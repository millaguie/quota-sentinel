# Quota Sentinel

Centralized AI provider quota monitoring daemon. Tracks usage and rate-limit
status across multiple AI coding providers, delivers real-time velocity analysis,
exhaustion projections, per-instance budget allocation, and **proactively switches
OpenCode to fallback models before credits run out**.

## Features

- **Multi-provider monitoring** -- Claude, GitHub Copilot, Z.ai, MiniMax,
  DeepSeek, and Alibaba Cloud (Tongyi Lingma)
- **Proactive model switching** -- automatically updates `opencode.json` to
  fallback models when a provider approaches quota exhaustion, with hysteresis
  to prevent flapping and automatic recovery when credits are replenished
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
pipx install .
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

| Command                  | Description                                      |
|--------------------------|--------------------------------------------------|
| `quota-sentinel start`   | Launch the daemon                                |
| `quota-sentinel status`  | Global daemon status                            |
| `quota-sentinel health`  | Health check                                     |
| `quota-sentinel switch`  | Proactively switch OpenCode models based on quota |

## API

All endpoints live under `/v1`.

### Instance management

| Method   | Path                              | Description                                    |
|----------|-----------------------------------|------------------------------------------------|
| `POST`   | `/v1/instances`                   | Register returns instance_id AND api_key (save this!) |
| `DELETE`  | `/v1/instances/{id}`             | Deregister instance                            |
| `PATCH`  | `/v1/instances/{id}/heartbeat`    | Keep-alive with optional state update          |

### Registration Options

The `POST /v1/instances` endpoint accepts different auth formats:

#### 1. OpenCode providers (ZAI, DeepSeek, MiniMax, Alibaba)

```json
{
  "project_name": "my-project",
  "framework": "opencode",
  "auth": {
    "opencode_auth": {
      "PROVIDER_KEY": {"key": "api-key"}
    }
  }
}
```

**Valid provider keys:**
| Auth Key | Provider | Notes |
|----------|----------|-------|
| `zai-coding-plan` or `zai` | zai | Z.ai |
| `deepseek-coding-plan` or `deepseek` | deepseek | DeepSeek |
| `minimax-coding-plan` or `minimax` | minimax | MiniMax |
| `bailian-coding-plan` or `alibaba-coding-plan` or `dashscope` or `alibaba` | alibaba | Alibaba Cloud |

#### 2. Claude (Anthropic OAuth)

```json
{
  "project_name": "my-project",
  "framework": "claude",
  "auth": {
    "claude_credentials": {
      "accessToken": "...",
      "refreshToken": "...",
      "expiresAt": 1234567890000
    }
  }
}
```

#### 3. GitHub Copilot

```json
{
  "project_name": "my-project",
  "framework": "opencode",
  "auth": {
    "github_token": "gho_..."
  }
}
```

#### 4. Full example with all options

```json
{
  "project_name": "my-project",
  "framework": "opencode",
  "poll_interval": 300,
  "provider_config": {
    "minimax": {"group_id": "group-123"},
    "copilot": {"github_username": "myuser", "plan": "pro"}
  },
  "hard_caps": {
    "deepseek_default": 90.0,
    "claude_five_hour": 70.0
  },
  "auth": {
    "opencode_auth": {
      "deepseek-coding-plan": {"key": "sk-..."},
      "minimax-coding-plan": {"key": "sk-...", "group_id": "group-123"}
    },
    "claude_credentials": {
      "accessToken": "...",
      "refreshToken": "...",
      "expiresAt": 1234567890000
    },
    "github_token": "gho_..."
  }
}
```

**Optional fields:**
| Field | Description |
|-------|-------------|
| `poll_interval` | Poll frequency in seconds (default: 300, min: 30) |
| `provider_config` | Provider-specific settings (see below) |
| `hard_caps` | Override default hard caps per provider |

**provider_config options:**
| Provider | Options |
|----------|---------|
| minimax | `group_id`: string |
| copilot | `github_username`: string, `plan`: "pro" or "business" |

### Status & monitoring

| Method  | Path                  | Description                                             |
|---------|-----------------------|---------------------------------------------------------|
| `GET`   | `/v1/status`          | Instance-specific status (requires X-API-Key header)    |
| `GET`   | `/v1/status/{id}`     | Single-instance TOKEN_STATUS with recommendation        |
| `GET`   | `/v1/providers`       | Instance providers (requires X-API-Key header)          |
| `GET`   | `/v1/providers/{name}`| Detailed provider info with subscriber list             |
| `POST`  | `/v1/poll`            | Trigger repoll (requires X-API-Key header)              |
| `GET`   | `/v1/health`          | Server health check                                     |

### GET /v1/providers

Returns a dict of provider name → status. Empty `{}` if no instances registered.

```json
{
  "deepseek": {
    "status": "GREEN",
    "windows": {
      "rolling": {
        "utilization": 45.2,
        "velocity_pct_per_hour": 5.3,
        "resets_at": "2026-04-10T00:00:00+00:00",
        "status": "GREEN",
        "metadata": {
          "total_balance": 2500.50,
          "is_available": true,
          "currency": "USD"
        }
      }
    }
  }
}
```

### GET /v1/providers/{name}

```json
{
  "name": "deepseek",
  "fingerprint": "abc123...",
  "subscribers": ["instance-id-1", "instance-id-2"],
  "windows": {
    "rolling": {
      "utilization": 45.2,
      "resets_at": "2026-04-10T00:00:00+00:00"
    }
  }
}
```

Or if no data:
```json
{
  "name": "deepseek",
  "status": "UNKNOWN",
  "error": "no data"
}
```

### Proactive Model Switching (OpenCode)

The `quota-sentinel switch` command monitors Quota Sentinel and proactively updates your `opencode.json` before you hit rate limits:

```bash
quota-sentinel switch /path/to/opencode.json --recovery-hold 5
```

**How it works:**
- Monitors providers and switches to fallback models when reaching YELLOW/RED status
- Uses hysteresis to prevent flapping (only restores after GREEN consecutive polls)
- Remembers original models across restarts via `.opencode-switcher.json`
- Works with any `opencode.json` file and supports multiple instances

### Agent Caddy Fallback Format

The model switcher expects `fallback_models` to be defined in your `opencode.json` using the Agent Caddy format:

**Basic Structure:**
```json
{
  "agent": {
    "YOUR_AGENT_NAME": {
      "model": "original-provider/original-model",
      "fallback_models": [
        "fallback-provider/fallback-model",
        "backup-provider/backup-model"
      ]
    }
  }
}
```

**Key Requirements:**

1. **Model Identifier Format**: Must be `provider/model-name` (e.g., `deepseek/deepseek-v3.2`)

2. **Provider Matching**: The switcher uses the prefix before `/` to match against Quota Sentinel provider names

3. **Selection Priority**: Fallback models are tried in order - first one with GREEN status is selected

**Complete Example:**
```json
{
  "agent": {
    "build": {
      "model": "github-copilot/gpt-5-mini",
      "fallback_models": [
        "deepseek/deepseek-v3.2",
        "alibaba/qwen3-max",
        "zai/glm-5.1"
      ]
    },
    "production": {
      "model": "deepseek/deepseek-v3.2",
      "fallback_models": [
        "alibaba/qwen3-max",
        "zai/glm-5.1"
      ]
    }
  }
}
```

**Selection Logic:**
1. When original provider reaches YELLOW/RED status
2. Iterates through `fallback_models` in order
3. Selects first model whose provider is currently GREEN
4. If all fallbacks are unhealthy, stays on current model
5. Recovery occurs only after original provider has been GREEN for `--recovery-hold` consecutive polls

### Agent Caddy Integration

If you use [Agent Caddy](https://github.com/millaguie/agentcaddy) to scaffold your projects,
`fallback_models` are generated automatically per agent based on model scoring and provider
diversity. No manual configuration needed — just run `agentcaddy generate` and the resulting
`opencode.json` will include fallbacks.

To integrate quota-sentinel switching into an Agent Caddy project, add a skill file
(e.g. `.opencode/skills/quota-sentinel.md`) so your agents know how to use it:

```markdown
## Quota Sentinel Management

Quota Sentinel monitors AI provider quotas and switches models proactively
before credits run out.

### Check if installed and running

```bash
command -v quota-sentinel          # check if installed
quota-sentinel health              # check if server is running
curl -s http://127.0.0.1:7878/v1/health
```

### Install (if not found)

```bash
pipx install git+https://github.com/millaguie/quota-sentinel.git
```

### Start the proactive switcher

```bash
quota-sentinel switch opencode.json          # daemon mode
quota-sentinel switch opencode.json --once   # single check and exit
quota-sentinel switch opencode.json --restore  # restore original models
```

### When asked to "set up quota-sentinel"

1. Check if installed: `command -v quota-sentinel`
2. If not installed: `pipx install git+https://github.com/millaguie/quota-sentinel.git`
3. Start the switcher: `quota-sentinel switch opencode.json &`
4. Confirm it started: `quota-sentinel health`
```

And define your agents with fallbacks in `data/catalog/agents.yaml`:

```yaml
agents:
  build:
    description: "Development agent - writes code, runs tests, builds the project"
    temperature: 0.2
    color: "#4CAF50"
    role: implementer
    domain: development

  test:
    description: "Test specialist - writes tests, validates coverage"
    temperature: 0.1
    color: "#8BC34A"
    role: tester
    domain: development
```

Agent Caddy's generator will automatically produce an `opencode.json` with
`fallback_models` for each agent, selecting the best alternative model from
different providers:

```json
{
  "agent": {
    "build": {
      "model": "github-copilot/gpt-5-mini",
      "fallback_models": [
        "deepseek/deepseek-v3.2",
        "alibaba/qwen3-max",
        "zai/glm-5.1"
      ]
    },
    "test": {
      "model": "github-copilot/gpt-5-mini",
      "fallback_models": [
        "deepseek/deepseek-v3.2",
        "alibaba/qwen3-max"
      ]
    }
  }
}
```

When `quota-sentinel switch` detects a provider approaching quota exhaustion,
it rewrites the `model` field to the first healthy fallback — transparently,
with no manual intervention.

## Authentication

All endpoints except `/v1/health` and `/v1/instances` require authentication
via the `X-API-Key` header.

### Register

```bash
curl -X POST http://127.0.0.1:7878/v1/instances \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "my-project",
    "framework": "opencode",
    "auth": {
      "opencode_auth": {
        "deepseek-coding-plan": {"key": "sk-..."}
      }
    }
  }'
```

Response:
```json
{
  "instance_id": "abc123...",
  "api_key": "qs_AbCdEfGhIjKlMnOpQrStUvWx",
  "providers": ["deepseek"],
  "poll_interval": 300
}
```

**Save the api_key** - you'll need it for all subsequent requests.

### Authenticated Requests

```bash
# Get status for your instance
curl -H "X-API-Key: qs_AbCdEfGhIjKlMnOpQrStUvWx" http://127.0.0.1:7878/v1/status

# Get your providers
curl -H "X-API-Key: qs_AbCdEfGhIjKlMnOpQrStUvWx" http://127.0.0.1:7878/v1/providers

# Trigger poll for your providers
curl -X POST -H "X-API-Key: qs_AbCdEfGhIjKlMnOpQrStUvWx" http://127.0.0.1:7878/v1/poll
```

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
6. **Clients query** with X-API-Key header for a recommendation
   (`PROCEED` / `PROCEED_SMALL_ONLY` / `STOP`) tailored to their framework.

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html).
