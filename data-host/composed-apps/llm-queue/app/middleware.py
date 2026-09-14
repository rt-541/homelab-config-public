"""ASGI middleware guarding the mounted /mcp app with the API bearer token.

Kept as raw ASGI (not Starlette's BaseHTTPMiddleware) on purpose: the MCP
streamable-HTTP transport returns long-lived SSE streams, and BaseHTTPMiddleware
buffers the response body, which would break streaming. This wrapper only
inspects request headers and either short-circuits a 401 or hands the request
through untouched.
"""
from __future__ import annotations

from .auth import token_is_valid


class MCPBearerAuth:
    """Require the API bearer token for any request under ``prefix`` (/mcp).

    Phase A relied on the edge LAN allowlist alone for /mcp; this closes that gap
    so the mount enforces the same token as the REST API. Phase B (LiteLLM key
    auth) only needs ``token_is_valid`` to change, in auth.py.
    """

    def __init__(self, app, prefix: str = "/mcp") -> None:
        self.app = app
        self.prefix = prefix

    def _guarded(self, path: str) -> bool:
        return path == self.prefix or path.startswith(self.prefix + "/")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and self._guarded(scope.get("path", "")):
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            if not await token_is_valid(headers.get("authorization"), headers.get("x-api-key")):
                await self._unauthorized(send)
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _unauthorized(send) -> None:
        body = b'{"detail":"invalid or missing API token"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
