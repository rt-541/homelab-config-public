"""Phase B auth: LiteLLM virtual key gate for API/MCP; session cookie for web UI.

The bearer/login token is a per-user LiteLLM virtual key, validated against the
gateway's /key/info endpoint. Owner becomes a hash of the key so jobs are scoped
per user. The web UI uses a signed session cookie carrying the same owner hash
plus the caller's key (see make_session_cookie / read_session_cookie); web routes
derive the owner from it via web._owner.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException
from itsdangerous import BadSignature, URLSafeTimedSerializer

OWNER_LOCAL = "local"
COOKIE_NAME = "llmq_session"
COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://llm-gateway:4000")
# /key/info probe auth: "self" (key validates itself) or "master" (use GATEWAY_MASTER_KEY).
GATEWAY_KEYINFO_AUTH = os.environ.get("GATEWAY_KEYINFO_AUTH", "self")
GATEWAY_MASTER_KEY = os.environ.get("GATEWAY_MASTER_KEY", "")


def owner_hash(key: str) -> str:
    return "k:" + hashlib.sha256(key.encode()).hexdigest()[:32]


async def _validate_key_remote(key: str) -> bool:
    """Return True if the gateway recognizes this virtual key. Fails closed."""
    bearer = GATEWAY_MASTER_KEY if GATEWAY_KEYINFO_AUTH == "master" else key
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{GATEWAY_URL}/key/info",
                params={"key": key},
                headers={"Authorization": f"Bearer {bearer}"},
            )
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def owner_for_token(token: str | None) -> str | None:
    """Validate a bearer/login token against the gateway; return its owner hash."""
    if not token:
        return None
    if not await _validate_key_remote(token):
        return None
    return owner_hash(token)


def _password() -> str:
    pw = os.environ.get("APP_PASSWORD")
    if not pw:
        raise RuntimeError("APP_PASSWORD is not set; refusing to start with a default credential")
    return pw


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET is not set; refusing to sign cookies with a default key")
    return URLSafeTimedSerializer(secret, salt="llmq-session")


def check_password(candidate: str) -> bool:
    return hmac.compare_digest(candidate or "", _password())


def make_session_cookie(owner: str, key: str) -> str:
    return _serializer().dumps({"owner": owner, "key": key})


def read_session_cookie(token: str) -> dict | None:
    try:
        data = _serializer().loads(token, max_age=COOKIE_MAX_AGE)
        if isinstance(data, dict) and "owner" in data and "key" in data:
            return data
        return None
    except (BadSignature, Exception):
        return None


def verify_session_cookie(token: str) -> bool:
    return read_session_cookie(token) is not None


# --- API / MCP bearer auth ---

def _extract_bearer(authorization: str | None, x_api_key: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_api_key:
        return x_api_key.strip()
    return None


async def token_is_valid(authorization: str | None, x_api_key: str | None) -> bool:
    """Header-only bearer check, for use outside the FastAPI dependency system
    (e.g. the raw-ASGI guard on the mounted /mcp app). Validates against the
    LiteLLM gateway. Fails closed on any error."""
    token = _extract_bearer(authorization, x_api_key)
    return await owner_for_token(token) is not None


async def require_api_auth(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> str:
    """Validate the API/MCP virtual key against the gateway; return owner hash."""
    token = _extract_bearer(authorization, x_api_key)
    owner = await owner_for_token(token)
    if owner is None:
        raise HTTPException(status_code=401, detail="invalid or missing API token")
    return owner


@dataclass
class Caller:
    owner: str
    key: str


async def require_caller(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> "Caller":
    token = _extract_bearer(authorization, x_api_key)
    owner = await owner_for_token(token)
    if owner is None:
        raise HTTPException(status_code=401, detail="invalid or missing API token")
    return Caller(owner=owner, key=token)
