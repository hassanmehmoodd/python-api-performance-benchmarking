"""Behavior of the local demo API."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from demo_api.app import DEMO_PASSWORD, DEMO_TOKEN, DEMO_USERNAME, app

client = TestClient(app)


def test_index_and_health() -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["cache-control"] == "no-store"
    assert "GET /api/secure/profile" in index.json()["endpoints"]
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_items_and_missing_item() -> None:
    listing = client.get("/api/items", params={"limit": 2})
    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 2
    assert body["items"][0]["id"] == 1
    assert client.get("/api/items", params={"limit": 0}).status_code == 422
    detail = client.get("/api/items/7")
    assert detail.status_code == 200
    assert detail.json()["sku"] == "SKU-0007"
    assert client.get("/api/items/999").status_code == 404


def test_db_orders_wait_and_compute_digest() -> None:
    started = time.perf_counter()
    response = client.get("/api/db/orders", params={"delay_ms": 80})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert response.json()["simulated_delay_ms"] == 80
    assert len(response.json()["orders"]) == 3
    assert elapsed >= 0.06

    digest = client.get("/api/compute/digest", params={"rounds": 10})
    assert digest.status_code == 200
    body = digest.json()
    assert body["algorithm"] == "sha256"
    assert body["rounds"] == 10
    assert len(body["digest"]) == 64
    assert client.get("/api/compute/digest", params={"rounds": 0}).status_code == 422


def test_token_and_profile() -> None:
    denied = client.post("/auth/token", json={"username": DEMO_USERNAME, "password": "nope"})
    assert denied.status_code == 401
    issued = client.post(
        "/auth/token",
        json={"username": DEMO_USERNAME, "password": DEMO_PASSWORD},
    )
    assert issued.status_code == 200
    assert issued.json()["access_token"] == DEMO_TOKEN
    assert issued.json()["token_type"] == "bearer"

    open_profile = client.get("/api/secure/profile")
    assert open_profile.status_code == 401
    wrong = client.get("/api/secure/profile", headers={"Authorization": "Bearer wrong-token"})
    assert wrong.status_code == 401
    allowed = client.get(
        "/api/secure/profile",
        headers={"Authorization": f"Bearer {DEMO_TOKEN}"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["username"] == DEMO_USERNAME


def test_flaky_modes() -> None:
    ok = client.get("/api/flaky", params={"mode": "ok", "delay_ms": 0})
    assert ok.status_code == 200
    error = client.get("/api/flaky", params={"mode": "error", "status_code": 503})
    assert error.status_code == 503
    assert client.get("/api/flaky", params={"mode": "slow", "delay_ms": 10}).status_code == 400
    started = time.perf_counter()
    slow = client.get("/api/flaky", params={"mode": "slow", "delay_ms": 50})
    assert slow.status_code == 200
    assert time.perf_counter() - started >= 0.04
    assert client.get("/api/flaky", params={"mode": "explode"}).status_code == 422
    assert client.get("/openapi.json").status_code == 200
