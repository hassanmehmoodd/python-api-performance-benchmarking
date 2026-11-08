"""Local FastAPI application used as the default benchmark target.

The service is deliberately small. It exposes fast reads, a query with an
injected delay, a CPU-bound digest, a fixed local bearer token, and a
fault-injection endpoint. Start it on the loopback interface and point the
benchmark at it. The token below is a demo fixture, not a credential.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo-pass"
DEMO_TOKEN = "local-demo-token"

_ITEMS: tuple[dict[str, int | str], ...] = tuple(
    {"id": index, "sku": f"SKU-{index:04d}", "name": f"Item {index}"} for index in range(1, 51)
)
_ORDERS: tuple[dict[str, int | float], ...] = (
    {"id": 501, "total": 42.5},
    {"id": 502, "total": 18.0},
    {"id": 503, "total": 7.25},
)

app = FastAPI(
    title="Local Benchmark Demo API",
    version="1.0.0",
    summary="Loopback target for the async API performance benchmark.",
)


class Item(BaseModel):
    id: int
    sku: str
    name: str


class ItemList(BaseModel):
    items: list[Item]
    count: int


class Order(BaseModel):
    id: int
    total: float


class OrderList(BaseModel):
    orders: list[Order]
    simulated_delay_ms: int


class DigestResult(BaseModel):
    algorithm: Literal["sha256"]
    rounds: int
    digest: str


class TokenRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int


class Profile(BaseModel):
    username: str
    role: str


class FlakyResult(BaseModel):
    status: Literal["ok"]
    mode: str
    delay_ms: int


def _matches(candidate: str, expected: str) -> bool:
    return hmac.compare_digest(candidate.encode(), expected.encode())


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


@app.middleware("http")
async def _no_store(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
async def index() -> dict[str, object]:
    return {
        "service": "local-benchmark-demo",
        "purpose": "Loopback target for api-performance-benchmark. Not a production service.",
        "endpoints": [
            "GET /health",
            "GET /api/items",
            "GET /api/items/{item_id}",
            "GET /api/db/orders",
            "GET /api/compute/digest",
            "POST /auth/token",
            "GET /api/secure/profile",
            "GET /api/flaky",
        ],
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/items", response_model=ItemList)
async def list_items(limit: int = Query(20, ge=1, le=50)) -> ItemList:
    selected = [Item.model_validate(item) for item in _ITEMS[:limit]]
    return ItemList(items=selected, count=len(selected))


@app.get("/api/items/{item_id}", response_model=Item)
async def get_item(item_id: int) -> Item:
    for item in _ITEMS:
        if item["id"] == item_id:
            return Item.model_validate(item)
    raise HTTPException(status_code=404, detail="item not found")


@app.get("/api/db/orders", response_model=OrderList)
async def list_orders(delay_ms: int = Query(25, ge=0, le=5_000)) -> OrderList:
    """Return a fixed order list after an injected wait.

    The wait stands in for a database round trip so latency sweeps have a
    stable, configurable cost.
    """

    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)
    return OrderList(
        orders=[Order.model_validate(order) for order in _ORDERS],
        simulated_delay_ms=delay_ms,
    )


@app.get("/api/compute/digest", response_model=DigestResult)
def compute_digest(rounds: int = Query(2_000, ge=1, le=100_000)) -> DigestResult:
    """Hash a fixed payload repeatedly.

    This is a sync endpoint, so FastAPI runs it in the thread pool. That keeps
    the event loop free and makes the concurrency sweep measure CPU work
    instead of head-of-line blocking.
    """

    digest = b"local-benchmark-payload"
    for _ in range(rounds):
        digest = hashlib.sha256(digest).digest()
    return DigestResult(algorithm="sha256", rounds=rounds, digest=digest.hex())


@app.post("/auth/token", response_model=TokenResponse)
async def issue_token(body: TokenRequest) -> TokenResponse:
    if not (_matches(body.username, DEMO_USERNAME) and _matches(body.password, DEMO_PASSWORD)):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return TokenResponse(access_token=DEMO_TOKEN, token_type="bearer", expires_in=3600)


@app.get("/api/secure/profile", response_model=Profile)
async def profile(authorization: str | None = Header(default=None)) -> Profile:
    token = _bearer_token(authorization)
    if token is None or not _matches(token, DEMO_TOKEN):
        raise HTTPException(status_code=401, detail="unauthorized")
    return Profile(username=DEMO_USERNAME, role="benchmark-client")


@app.get("/api/flaky", response_model=FlakyResult)
async def flaky(
    mode: str = Query("ok", pattern="^(ok|error|slow)$"),
    delay_ms: int = Query(0, ge=0, le=5_000),
    status_code: int = Query(503, ge=400, le=599),
) -> FlakyResult:
    """Configurable fault injection.

    ``mode=error`` returns ``status_code`` after the delay. ``mode=slow`` waits
    ``delay_ms`` and then returns 200, which is how client-timeout scenarios
    are produced. ``mode=ok`` returns 200 after the same delay.
    """

    if mode == "slow" and delay_ms < 50:
        raise HTTPException(status_code=400, detail="slow mode requires delay_ms >= 50")
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)
    if mode == "error":
        raise HTTPException(status_code=status_code, detail="injected error")
    return FlakyResult(status="ok", mode=mode, delay_ms=delay_ms)
