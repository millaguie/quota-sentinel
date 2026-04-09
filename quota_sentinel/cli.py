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
@click.option("--poll-interval", default=300, type=int, help="Default poll interval (seconds)")
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
    uvicorn.run(app, host=host, port=port, log_level="warning")


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
