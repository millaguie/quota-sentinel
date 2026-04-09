"""OpenAPI documentation — SchemaGenerator + ReDoc UI."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.schemas import SchemaGenerator

OPENAPI_BASE: dict = {
    "openapi": "3.1.0",
    "info": {
        "title": "Quota Sentinel",
        "description": "Centralized AI provider quota monitoring daemon.",
        "version": "0.1.0",
        "license": {
            "name": "GPL-3.0-or-later",
            "url": "https://www.gnu.org/licenses/gpl-3.0.html",
        },
    },
    "servers": [{"url": "http://127.0.0.1:7878", "description": "Local development"}],
    "tags": [
        {"name": "instances", "description": "Instance lifecycle management"},
        {"name": "status", "description": "Status and monitoring"},
        {"name": "providers", "description": "Provider information"},
        {"name": "operations", "description": "Operational controls"},
    ],
    "components": {
        "parameters": {
            "InstanceId": {
                "name": "id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "Instance identifier (SHA-256 prefix, 12 chars).",
            },
        },
        "schemas": {
            # ── Enums ──────────────────────────────────────────
            "HealthStatus": {
                "type": "string",
                "enum": ["GREEN", "YELLOW", "RED", "UNKNOWN"],
            },
            "Recommendation": {
                "type": "string",
                "enum": ["PROCEED", "PROCEED_SMALL_ONLY", "STOP"],
            },
            "Framework": {
                "type": "string",
                "enum": ["opencode", "claude"],
                "default": "opencode",
            },
            "InstanceState": {
                "type": "string",
                "enum": ["active", "idle", "paused"],
                "default": "active",
            },
            # ── Common ─────────────────────────────────────────
            "Error": {
                "type": "object",
                "required": ["error"],
                "properties": {"error": {"type": "string"}},
            },
            "StatusOk": {
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"type": "string", "const": "ok"}},
            },
            # ── Instances ──────────────────────────────────────
            "AuthCredentials": {
                "type": "object",
                "description": "At least one credential source must be provided.",
                "properties": {
                    "opencode_auth": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "required": ["key"],
                            "properties": {"key": {"type": "string"}},
                        },
                    },
                    "claude_credentials": {
                        "type": "object",
                        "required": ["accessToken"],
                        "properties": {
                            "accessToken": {"type": "string"},
                            "refreshToken": {"type": "string"},
                            "expiresAt": {
                                "type": "number",
                                "description": "Unix timestamp.",
                            },
                        },
                    },
                    "github_token": {"type": "string"},
                },
            },
            "RegisterInstanceRequest": {
                "type": "object",
                "required": ["project_name", "auth"],
                "properties": {
                    "project_name": {"type": "string"},
                    "auth": {"$ref": "#/components/schemas/AuthCredentials"},
                    "framework": {"$ref": "#/components/schemas/Framework"},
                    "poll_interval": {
                        "type": "integer",
                        "minimum": 30,
                        "default": 300,
                        "description": "Seconds between provider polls.",
                    },
                    "provider_config": {
                        "type": "object",
                        "additionalProperties": {"type": "object"},
                        "description": "Provider-specific config overrides.",
                    },
                    "hard_caps": {
                        "type": "object",
                        "additionalProperties": {"type": "number"},
                        "description": "Per-instance hard-cap overrides.",
                    },
                },
            },
            "RegisterInstanceResponse": {
                "type": "object",
                "required": ["instance_id", "providers", "poll_interval"],
                "properties": {
                    "instance_id": {"type": "string"},
                    "providers": {"type": "array", "items": {"type": "string"}},
                    "poll_interval": {"type": "integer"},
                },
            },
            # ── Windows ────────────────────────────────────────
            "WindowStatus": {
                "type": "object",
                "required": ["utilization", "velocity_pct_per_hour", "status"],
                "properties": {
                    "utilization": {"type": "number", "minimum": 0, "maximum": 100},
                    "velocity_pct_per_hour": {"type": "number"},
                    "projected_exhaustion_min": {
                        "type": "integer",
                        "nullable": True,
                        "description": "Minutes until hard cap; null if steady/declining.",
                    },
                    "resets_at": {
                        "type": "string",
                        "format": "date-time",
                        "nullable": True,
                    },
                    "status": {"$ref": "#/components/schemas/HealthStatus"},
                },
            },
            # ── Instance status (TOKEN_STATUS) ─────────────────
            "InstanceStatus": {
                "type": "object",
                "required": [
                    "timestamp",
                    "framework",
                    "overall_status",
                    "recommendation",
                    "message",
                    "providers",
                    "all_exhausted",
                    "central_watchdog",
                ],
                "properties": {
                    "timestamp": {"type": "string", "format": "date-time"},
                    "framework": {"$ref": "#/components/schemas/Framework"},
                    "overall_status": {"$ref": "#/components/schemas/HealthStatus"},
                    "recommendation": {"$ref": "#/components/schemas/Recommendation"},
                    "message": {"type": "string"},
                    "providers": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "required": ["status"],
                            "properties": {
                                "status": {"$ref": "#/components/schemas/HealthStatus"},
                                "error": {"type": "string"},
                                "windows": {
                                    "type": "object",
                                    "additionalProperties": {
                                        "$ref": "#/components/schemas/WindowStatus",
                                    },
                                },
                            },
                        },
                    },
                    "alternative_providers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "GREEN providers (opencode only).",
                    },
                    "all_exhausted": {"type": "boolean"},
                    "central_watchdog": {
                        "type": "object",
                        "required": ["active_instances", "budget_weight", "mode"],
                        "properties": {
                            "active_instances": {"type": "integer"},
                            "budget_weight": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "mode": {"type": "string", "const": "centralized"},
                        },
                    },
                },
            },
            # ── Provider ───────────────────────────────────────
            "ProviderSummary": {
                "type": "object",
                "required": ["status"],
                "properties": {
                    "status": {"$ref": "#/components/schemas/HealthStatus"},
                    "error": {"type": "string"},
                    "windows": {
                        "type": "object",
                        "additionalProperties": {
                            "$ref": "#/components/schemas/WindowStatus"
                        },
                    },
                },
            },
            "ProviderDetail": {
                "type": "object",
                "required": ["name", "fingerprint", "subscribers"],
                "properties": {
                    "name": {"type": "string"},
                    "fingerprint": {"type": "string"},
                    "subscribers": {"type": "array", "items": {"type": "string"}},
                    "error": {"type": "string"},
                    "windows": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "properties": {
                                "utilization": {"type": "number"},
                                "resets_at": {
                                    "type": "string",
                                    "format": "date-time",
                                    "nullable": True,
                                },
                            },
                        },
                    },
                },
            },
            # ── Health ─────────────────────────────────────────
            "HealthResponse": {
                "type": "object",
                "required": ["status", "uptime", "providers", "instances"],
                "properties": {
                    "status": {"type": "string", "const": "ok"},
                    "uptime": {"type": "integer"},
                    "providers": {"type": "integer"},
                    "instances": {"type": "integer"},
                },
            },
        },
    },
}

schemas = SchemaGenerator(OPENAPI_BASE)


async def openapi_schema(request: Request) -> JSONResponse:
    """
    summary: OpenAPI schema
    responses:
      200:
        description: OpenAPI 3.1 specification (JSON).
    """
    return JSONResponse(schemas.get_schema(routes=request.app.routes))


_REDOC_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <title>Quota Sentinel &mdash; API</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>body { margin: 0; padding: 0; }</style>
</head>
<body>
  <redoc spec-url="/v1/openapi.json"></redoc>
  <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>
"""


async def redoc_ui(request: Request) -> HTMLResponse:
    """
    summary: ReDoc interactive documentation
    responses:
      200:
        description: ReDoc HTML page.
        content:
          text/html: {}
    """
    return HTMLResponse(_REDOC_HTML)
