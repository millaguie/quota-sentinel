#!/usr/bin/env python3
"""E2E tests for quota-sentinel - simulates a client interacting with the daemon."""

from __future__ import annotations

import json
import sys
import time
import subprocess
import requests

SERVER_URL = "http://127.0.0.1:7878"
STARTUP_TIMEOUT = 30


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """Wait for server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{url}/v1/health", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False


def test_health_check():
    """Test that the server responds to health check."""
    resp = requests.get(f"{SERVER_URL}/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    print("✓ Health check passed")


def test_global_status():
    """Test global status endpoint."""
    resp = requests.get(f"{SERVER_URL}/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "instances" in data
    assert "providers" in data
    print("✓ Global status passed")


def test_register_instance():
    """Test instance registration."""
    payload = {
        "project_name": "test-project",
        "framework": "opencode",
        "poll_interval": 60,
        "auth": {"opencode_auth": {"zai-coding-plan": {"key": "test-key-for-e2e"}}},
    }
    resp = requests.post(f"{SERVER_URL}/v1/instances", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    instance_id = data["instance_id"]
    assert instance_id is not None
    print(f"✓ Instance registration passed (id: {instance_id})")
    return instance_id


def test_instance_status(instance_id: str):
    """Test getting instance status."""
    resp = requests.get(f"{SERVER_URL}/v1/status/{instance_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_status" in data
    assert "recommendation" in data
    print(f"✓ Instance status passed")


def test_heartbeat(instance_id: str):
    """Test heartbeat."""
    resp = requests.patch(
        f"{SERVER_URL}/v1/instances/{instance_id}/heartbeat", json={"state": "active"}
    )
    assert resp.status_code == 200
    print(f"✓ Heartbeat passed")


def test_deregister_instance(instance_id: str):
    """Test instance deregistration."""
    resp = requests.delete(f"{SERVER_URL}/v1/instances/{instance_id}")
    assert resp.status_code == 200
    print(f"✓ Deregister passed")


def main():
    """Run all E2E tests."""
    print("Waiting for server to be ready...")
    if not wait_for_server(SERVER_URL, STARTUP_TIMEOUT):
        print("ERROR: Server did not become ready in time")
        sys.exit(1)

    print("\n=== E2E Tests ===\n")

    # Run tests
    test_health_check()
    test_global_status()
    instance_id = test_register_instance()
    test_instance_status(instance_id)
    test_heartbeat(instance_id)
    test_deregister_instance(instance_id)

    print("\n=== All E2E tests passed ===\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
