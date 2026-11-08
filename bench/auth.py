"""Acquire a bearer token from the local demo, or from an authorized target."""

from __future__ import annotations

import httpx

from bench.config import AuthConfig
from bench.runner_timeout import request_timeout


class AuthenticationError(RuntimeError):
    """Token acquisition failed. The password is never included in the message."""


def classify_exception(exc: BaseException) -> str:
    """Map an HTTPX failure onto a stable category."""

    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.WriteTimeout):
        return "write_timeout"
    if isinstance(exc, httpx.PoolTimeout):
        return "pool_timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if isinstance(exc, httpx.RequestError):
        return "request_error"
    return "unexpected_error"


async def acquire_token(client: httpx.AsyncClient, auth: AuthConfig, timeout: float) -> str:
    try:
        response = await client.post(
            auth.token_path,
            json={"username": auth.username, "password": auth.password},
            timeout=request_timeout(timeout),
        )
    except httpx.RequestError as exc:
        raise AuthenticationError(
            f"Token request to {auth.token_path} failed ({classify_exception(exc)})."
        ) from exc
    if response.status_code != 200:
        raise AuthenticationError(
            f"Token request to {auth.token_path} failed with status {response.status_code}."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AuthenticationError("Token response was not JSON.") from exc
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise AuthenticationError("Token response did not include access_token.")
    return token
