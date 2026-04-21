"""CLI for quota-sentinel."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

import click

from quota_sentinel.config import ServerConfig


@click.group()
def cli() -> None:
    """Quota Sentinel — centralized AI provider quota monitoring daemon."""


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind address")
@click.option("--port", default=7878, type=int, help="Bind port")
@click.option(
    "--poll-interval", default=300, type=int, help="Default poll interval (seconds)"
)
def start(host: str, port: int, poll_interval: int) -> None:
    """Start the quota-sentinel daemon."""
    import logging
    import uvicorn

    from quota_sentinel.server import create_app

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = ServerConfig(
        host=host,
        port=port,
        default_poll_interval=poll_interval,
    )
    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level="info")


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=7878, type=int)
def status(host: str, port: int) -> None:
    """Show daemon status."""
    url = f"http://{host}:{port}/v1/status"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        click.echo(json.dumps(data, indent=2))
    except urllib.error.URLError as e:
        click.echo(f"Error: cannot reach daemon at {url} — {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=7878, type=int)
def health(host: str, port: int) -> None:
    """Health check."""
    url = f"http://{host}:{port}/v1/health"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        click.echo(json.dumps(data, indent=2))
    except urllib.error.URLError as e:
        click.echo(f"Error: cannot reach daemon at {url} — {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("opencode_json", default="opencode.json", type=click.Path(exists=True))
@click.option("--sentinel-url", default="http://127.0.0.1:7878", show_default=True)
@click.option(
    "--poll-interval",
    default=60,
    type=int,
    show_default=True,
    help="Seconds between quota checks.",
)
@click.option(
    "--recovery-hold",
    default=3,
    type=int,
    show_default=True,
    help="Consecutive GREEN polls before restoring original model.",
)
@click.option("--once", is_flag=True, help="Run one check cycle and exit.")
@click.option(
    "--restore", is_flag=True, help="Restore all agents to original models and exit."
)
def switch(
    opencode_json: str,
    sentinel_url: str,
    poll_interval: int,
    recovery_hold: int,
    once: bool,
    restore: bool,
) -> None:
    """Proactively switch OpenCode models when quota is running low.

    Monitors Quota Sentinel and updates OPENCODE_JSON model assignments
    before quota is exhausted, using fallback_models from the config.
    Restores original models when the provider recovers (after
    --recovery-hold consecutive GREEN polls, to prevent flapping).

    \b
    Examples:
      quota-sentinel switch                        # daemon mode, current dir
      quota-sentinel switch --once                 # single check and exit
      quota-sentinel switch --restore              # restore originals and exit
      quota-sentinel switch /path/to/opencode.json # explicit path
    """
    import logging
    from pathlib import Path

    from quota_sentinel.switcher import ModelSwitcher

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    switcher = ModelSwitcher(
        opencode_json=Path(opencode_json),
        sentinel_url=sentinel_url,
        poll_interval=poll_interval,
        recovery_hold=recovery_hold,
    )

    if restore:
        switcher._init_state()
        n = switcher.restore_all()
        click.echo(f"Restored {n} agent(s) to original models.")
        return

    if once:
        switcher._init_state()
        if not switcher._register():
            click.echo("Error: could not register with Quota Sentinel", err=True)
            sys.exit(1)
        try:
            result = switcher.poll_once()
            click.echo(json.dumps(result, indent=2))
        finally:
            switcher._deregister()
        return

    switcher.run()
