"""Starlette HTTP server — API endpoints for quota-sentinel."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from quota_sentinel.config import ServerConfig
from quota_sentinel.daemon import build_instance_status, run_loop
from quota_sentinel.docs import openapi_schema, redoc_ui
from quota_sentinel.providers import AUTH_KEY_TO_PROVIDER, create_provider
from quota_sentinel.store import InstanceEntry, Store

logger = logging.getLogger(__name__)

# Module-level references set during lifespan
_store: Store | None = None
_config: ServerConfig | None = None


def _get_store() -> Store:
    assert _store is not None
    return _store


def _get_config() -> ServerConfig:
    assert _config is not None
    return _config


def _get_instance_from_request(request: Request) -> InstanceEntry | None:
    """Look up instance by X-API-Key header.

    Returns the InstanceEntry if a valid API key is provided, None otherwise.
    """
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return None

    store = _get_store()
    for entry in store.instances.values():
        if entry.api_key == api_key:
            return entry
    return None


def _require_auth(request: Request) -> JSONResponse | None:
    """Check auth and return 401 response if invalid, None if valid."""
    if _get_instance_from_request(request) is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


# ── Instance registration ──────────────────────────────────────────


def _build_providers_from_auth(
    auth: dict[str, Any], provider_config: dict[str, Any]
) -> tuple[
    dict[str, Any],  # {provider_name: UsageProvider}
    dict[str, str],  # {provider_name: raw_key} for fingerprinting
]:
    """Parse client auth payload and instantiate providers.

    auth format:
    {
        "opencode_auth": {"zai-coding-plan": {"key": "sk-..."}, ...},
        "claude_credentials": {"accessToken": "...", "refreshToken": "...", "expiresAt": ...},
        "github_token": "gho_..."
    }
    """
    providers = {}
    keys = {}

    # OpenCode auth keys
    oc_auth = auth.get("opencode_auth", {})
    for auth_key, entry in oc_auth.items():
        if not isinstance(entry, dict) or not entry.get("key"):
            continue
        pname = AUTH_KEY_TO_PROVIDER.get(auth_key)
        if not pname or pname in providers:
            continue

        cfg: dict[str, Any] = {"key": entry["key"]}
        # Merge provider-specific config
        if pname in provider_config:
            cfg.update(provider_config[pname])

        try:
            providers[pname] = create_provider(pname, cfg)
            keys[pname] = entry["key"]
        except (ValueError, KeyError) as e:
            logger.warning("Skipping provider %s: %s", pname, e)

    # Claude credentials
    claude_creds = auth.get("claude_credentials", {})
    if claude_creds.get("accessToken") and "claude" not in providers:
        cfg = {
            "access_token": claude_creds["accessToken"],
            "refresh_token": claude_creds.get("refreshToken", ""),
            "expires_at": claude_creds.get("expiresAt", 0),
        }
        try:
            providers["claude"] = create_provider("claude", cfg)
            keys["claude"] = claude_creds["accessToken"]
        except (ValueError, KeyError) as e:
            logger.warning("Skipping claude: %s", e)

    # GitHub token for Copilot
    gh_token = auth.get("github_token", "")
    if gh_token and "copilot" not in providers:
        gh_cfg = provider_config.get("copilot", {})
        cfg = {
            "github_token": gh_token,
            "github_username": gh_cfg.get("github_username", ""),
            "plan": gh_cfg.get("plan", "pro"),
        }
        if cfg["github_username"]:
            try:
                providers["copilot"] = create_provider("copilot", cfg)
                keys["copilot"] = gh_token
            except (ValueError, KeyError) as e:
                logger.warning("Skipping copilot: %s", e)

    return providers, keys


async def register_instance(request: Request) -> JSONResponse:
    """
    tags:
      - instances
    summary: Register a new client instance
    requestBody:
      required: true
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/RegisterInstanceRequest'
    responses:
      201:
        description: Instance registered.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RegisterInstanceResponse'
      400:
        description: Invalid request.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    store = _get_store()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    project_name = body.get("project_name", "")
    if not project_name:
        return JSONResponse({"error": "project_name required"}, status_code=400)

    auth = body.get("auth", {})
    if not auth:
        return JSONResponse({"error": "auth required"}, status_code=400)

    framework = body.get("framework", "opencode")
    poll_interval = max(int(body.get("poll_interval", 300)), 30)
    provider_config = body.get("provider_config", {})
    hard_caps = body.get("hard_caps", {})

    # Generate instance_id
    instance_id = hashlib.sha256(
        f"{project_name}:{time.time()}".encode(),
    ).hexdigest()[:12]

    # Build providers from auth payload
    providers, keys = _build_providers_from_auth(auth, provider_config)
    if not providers:
        return JSONResponse(
            {"error": "no valid providers found in auth"}, status_code=400
        )

    entry = store.register_instance(
        instance_id=instance_id,
        project_name=project_name,
        framework=framework,
        poll_interval=poll_interval,
        providers=providers,
        keys=keys,
        hard_caps=hard_caps or None,
    )

    logger.info(
        "Registered instance %s (%s) with providers: %s",
        instance_id,
        project_name,
        store.provider_names_for_instance(instance_id),
    )

    return JSONResponse(
        {
            "instance_id": instance_id,
            "api_key": entry.api_key,
            "providers": store.provider_names_for_instance(instance_id),
            "poll_interval": entry.poll_interval,
        },
        status_code=201,
    )


async def deregister_instance(request: Request) -> JSONResponse:
    """
    tags:
      - instances
    summary: Deregister an instance
    parameters:
      - $ref: '#/components/parameters/InstanceId'
    responses:
      200:
        description: Instance removed.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/StatusOk'
      404:
        description: Instance not found.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    store = _get_store()
    instance_id = request.path_params["id"]
    if store.deregister_instance(instance_id):
        logger.info("Deregistered instance %s", instance_id)
        return JSONResponse({"status": "ok"})
    return JSONResponse({"error": "not found"}, status_code=404)


async def heartbeat(request: Request) -> JSONResponse:
    """
    tags:
      - instances
    summary: Send heartbeat and optionally update state
    parameters:
      - $ref: '#/components/parameters/InstanceId'
    requestBody:
      content:
        application/json:
          schema:
            type: object
            properties:
              state:
                $ref: '#/components/schemas/InstanceState'
    responses:
      200:
        description: Heartbeat acknowledged.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/StatusOk'
      401:
        description: Unauthorized.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
      404:
        description: Instance not found.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    auth_error = _require_auth(request)
    if auth_error:
        return auth_error

    store = _get_store()
    instance_id = request.path_params["id"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    state = body.get("state")
    if store.heartbeat(instance_id, state):
        return JSONResponse({"status": "ok"})
    return JSONResponse({"error": "not found"}, status_code=404)


# ── Status endpoints ────────────────────────────────────────────────


async def global_status(request: Request) -> JSONResponse:
    """
    tags:
      - status
    summary: Global daemon status
    description: Returns uptime, instance details, provider summaries, and budget allocations.
    responses:
      200:
        description: Current global state.
      401:
        description: Unauthorized.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    auth_error = _require_auth(request)
    if auth_error:
        return auth_error

    store = _get_store()

    summary = store.summary()

    # Build per-instance statuses
    allocations = getattr(store, "_last_allocations", {})
    instances_out = {}
    for iid, inst in store.instances.items():
        instances_out[iid] = {
            "project_name": inst.project_name,
            "framework": inst.framework,
            "state": inst.state,
            "providers": store.provider_names_for_instance(iid),
            "heartbeat_at": inst.heartbeat_at.isoformat(),
        }

    # Provider summaries
    providers_out: dict[str, Any] = {}
    for pe in store.unique_providers():
        pname = pe.provider_name
        if pe.last_result and not pe.last_result.error:
            windows = {}
            for wn, wd in pe.last_result.windows.items():
                tracker = store.velocities.get(pname, {}).get(wn)
                vel = tracker.velocity_pct_per_hour() if tracker else 0.0
                w: dict[str, Any] = {
                    "utilization": round(wd.utilization, 1),
                    "velocity_pct_per_hour": round(vel, 1),
                    "resets_at": wd.resets_at.isoformat() if wd.resets_at else None,
                }
                if wd.metadata:
                    w["metadata"] = wd.metadata
                windows[wn] = w
            providers_out[pname] = {
                "subscribers": len(pe.subscribers),
                "fingerprint": pe.fingerprint,
                "windows": windows,
            }
        elif pe.last_result:
            providers_out[pname] = {
                "subscribers": len(pe.subscribers),
                "fingerprint": pe.fingerprint,
                "error": pe.last_result.error,
            }

    return JSONResponse(
        {
            **summary,
            "timestamp": datetime.now(UTC).isoformat(),
            "instances": instances_out,
            "providers": providers_out,
            "allocations": {
                k: {ck: round(cv, 1) for ck, cv in v.items()}
                for k, v in allocations.items()
            },
        }
    )


async def instance_status(request: Request) -> JSONResponse:
    """
    tags:
      - status
    summary: Per-instance status with recommendation
    parameters:
      - $ref: '#/components/parameters/InstanceId'
    responses:
      200:
        description: TOKEN_STATUS with recommendation.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/InstanceStatus'
      404:
        description: Instance not found.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    store = _get_store()
    config = _get_config()
    instance_id = request.path_params["id"]

    if instance_id not in store.instances:
        return JSONResponse({"error": "not found"}, status_code=404)

    allocations = getattr(store, "_last_allocations", {})
    status = build_instance_status(instance_id, store, config, allocations)
    return JSONResponse(status)


async def providers_summary(request: Request) -> JSONResponse:
    """
    tags:
      - providers
    summary: Provider summary
    description: Compact provider overview suitable for dashboards and StreamDeck.
    responses:
      200:
        description: Map of provider names to their current status.
        content:
          application/json:
            schema:
              type: object
              additionalProperties:
                $ref: '#/components/schemas/ProviderSummary'
      401:
        description: Unauthorized.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    auth_error = _require_auth(request)
    if auth_error:
        return auth_error

    store = _get_store()
    config = _get_config()

    from quota_sentinel.engine import get_hard_cap, _window_status

    out: dict[str, Any] = {}
    for pe in store.unique_providers():
        pname = pe.provider_name
        if not pe.last_result or pe.last_result.error:
            out[pname] = {
                "status": "UNKNOWN",
                "error": pe.last_result.error if pe.last_result else "no data",
            }
            continue

        worst = "GREEN"
        status_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
        windows = {}
        for wn, wd in pe.last_result.windows.items():
            tracker = store.velocities.get(pname, {}).get(wn)
            vel = tracker.velocity_pct_per_hour() if tracker else 0.0
            cap = get_hard_cap(pname, wn, config.hard_caps)
            ws = _window_status(wd.utilization, vel, cap, config.safety_margin_min)
            w2: dict[str, Any] = {
                "utilization": round(wd.utilization, 1),
                "velocity_pct_per_hour": round(vel, 1),
                "resets_at": wd.resets_at.isoformat() if wd.resets_at else None,
                "status": ws,
            }
            if wd.metadata:
                w2["metadata"] = wd.metadata
            windows[wn] = w2
            if status_order.get(ws, 0) > status_order.get(worst, 0):
                worst = ws

        out[pname] = {"status": worst, "windows": windows}

    return JSONResponse(out)


async def provider_detail(request: Request) -> JSONResponse:
    """
    tags:
      - providers
    summary: Single provider detail
    parameters:
      - name: name
        in: path
        required: true
        schema:
          type: string
        description: Provider name (e.g. claude, copilot, zai-coding-plan).
    responses:
      200:
        description: Provider detail with subscriber list.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ProviderDetail'
      404:
        description: Provider not found.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    store = _get_store()
    name = request.path_params["name"]

    entries = [pe for pe in store.unique_providers() if pe.provider_name == name]
    if not entries:
        return JSONResponse({"error": "not found"}, status_code=404)

    pe = entries[0]
    result: dict[str, Any] = {
        "name": name,
        "fingerprint": pe.fingerprint,
        "subscribers": sorted(pe.subscribers),
    }
    if pe.last_result:
        if pe.last_result.error:
            result["error"] = pe.last_result.error
        else:
            windows_out = {}
            for wn, wd in pe.last_result.windows.items():
                w3: dict[str, Any] = {
                    "utilization": round(wd.utilization, 1),
                    "resets_at": wd.resets_at.isoformat() if wd.resets_at else None,
                }
                if wd.metadata:
                    w3["metadata"] = wd.metadata
                windows_out[wn] = w3
            result["windows"] = windows_out
    return JSONResponse(result)


async def trigger_poll(request: Request) -> JSONResponse:
    """
    tags:
      - operations
    summary: Trigger an immediate poll cycle
    responses:
      200:
        description: Poll triggered.
      401:
        description: Unauthorized.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Error'
    """
    auth_error = _require_auth(request)
    if auth_error:
        return auth_error

    store = _get_store()
    store.trigger_poll()
    return JSONResponse({"status": "poll triggered"})


async def health(request: Request) -> JSONResponse:
    """
    tags:
      - operations
    summary: Health check
    responses:
      200:
        description: Daemon is healthy.
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/HealthResponse'
    """
    store = _get_store()
    return JSONResponse(
        {
            "status": "ok",
            "uptime": round(store.uptime()),
            "providers": len(store.providers),
            "instances": len(store.instances),
        }
    )


# ── App factory ─────────────────────────────────────────────────────


routes = [
    Route("/v1/instances", register_instance, methods=["POST"]),
    Route("/v1/instances/{id}", deregister_instance, methods=["DELETE"]),
    Route("/v1/instances/{id}/heartbeat", heartbeat, methods=["PATCH"]),
    Route("/v1/status", global_status, methods=["GET"]),
    Route("/v1/status/{id}", instance_status, methods=["GET"]),
    Route("/v1/providers", providers_summary, methods=["GET"]),
    Route("/v1/providers/{name}", provider_detail, methods=["GET"]),
    Route("/v1/poll", trigger_poll, methods=["POST"]),
    Route("/v1/health", health, methods=["GET"]),
    Route("/v1/openapi.json", openapi_schema, methods=["GET"], include_in_schema=False),
    Route("/v1/docs", redoc_ui, methods=["GET"], include_in_schema=False),
]


def create_app(config: ServerConfig | None = None) -> Starlette:
    """Create the Starlette application."""
    global _store, _config  # noqa: PLW0603
    _config = config or ServerConfig()
    _store = Store(velocity_window=_config.velocity_window)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        poll_task = asyncio.create_task(run_loop(_store, _config))
        logger.info(
            "quota-sentinel listening on %s:%d",
            _config.host,
            _config.port,
        )
        yield
        poll_task.cancel()
        try:
            await asyncio.wait_for(poll_task, timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("quota-sentinel stopped")

    return Starlette(routes=routes, lifespan=lifespan)
