"""Streamable HTTP transport - run the connector as a hosted (remote) MCP server.

The stdio server only works for clients that can spawn a local process (Claude
Desktop, Claude Code). Serving over Streamable HTTP lets the same tools be added
as a remote connector (claude.ai "Add custom connector", mobile, other clients).

This is a SINGLE-ATHLETE deployment: the TrainingPeaks cookie comes from the
host's credential store (normally the TP_AUTH_COOKIE env var), so anyone who can
reach the endpoint acts as that athlete. Access is therefore gated by a shared
secret (TP_MCP_HTTP_TOKEN), accepted in either of two forms:

- Secret path:  https://host/<token>/mcp  - for clients that only take a URL
  (claude.ai custom connectors cannot send a static Authorization header).
- Bearer token: https://host/mcp + "Authorization: Bearer <token>" - for clients
  that can set headers (Claude Code ``--header``, scripts).

``/healthz`` is unauthenticated and reveals nothing beyond liveness.
"""

import hmac
import logging
import os

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from tp_mcp import __version__

logger = logging.getLogger("tp-mcp")

TOKEN_ENV_VAR = "TP_MCP_HTTP_TOKEN"
MIN_TOKEN_LENGTH = 32
MCP_PATH = "/mcp"
HEALTH_PATH = "/healthz"
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


async def _health(request: Request) -> Response:
    return JSONResponse({"status": "ok", "version": __version__})


class SecretGate:
    """ASGI middleware enforcing the shared-secret check in front of the MCP app.

    ``/<token>/mcp`` is rewritten to ``/mcp`` so the inner app sees one route.
    A bare ``/mcp`` request must carry ``Authorization: Bearer <token>``.
    With no token configured (loopback only) every request passes.
    """

    def __init__(self, app: ASGIApp, token: str | None):
        self.app = app
        self.token = token
        self._secret_prefix = f"/{token}" if token else None

    def _bearer_ok(self, scope: Scope) -> bool:
        assert self.token is not None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                scheme, _, presented = value.decode("latin-1").partition(" ")
                if scheme.lower() == "bearer":
                    return hmac.compare_digest(presented.strip().encode(), self.token.encode())
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.token is None:
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        if path == HEALTH_PATH:
            await self.app(scope, receive, send)
            return

        prefix = self._secret_prefix
        assert prefix is not None
        head, sep, rest = path[1:].partition("/")
        if sep and hmac.compare_digest(f"/{head}".encode(), prefix.encode()):
            inner = "/" + rest
            scope = {**scope, "path": inner, "raw_path": inner.encode()}
            await self.app(scope, receive, send)
            return

        if path.rstrip("/") == MCP_PATH and self._bearer_ok(scope):
            await self.app(scope, receive, send)
            return

        # 404 rather than 401 so the secret path's existence is not confirmed.
        await JSONResponse({"error": "not_found"}, status_code=404)(scope, receive, send)


def resolve_token(host: str) -> str | None:
    """Read and check the shared secret; raise ValueError if the config is unsafe."""
    token = os.environ.get(TOKEN_ENV_VAR, "").strip() or None
    if token is None:
        if host not in _LOOPBACK_HOSTS:
            raise ValueError(
                f"{TOKEN_ENV_VAR} must be set when binding to a non-loopback host ({host}). "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return None
    if len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"{TOKEN_ENV_VAR} must be at least {MIN_TOKEN_LENGTH} characters.")
    if not all(c.isalnum() or c in "-_" for c in token):
        raise ValueError(f"{TOKEN_ENV_VAR} may only contain letters, digits, '-' and '_' (it is used in the URL).")
    return token


def build_app(token: str | None, host: str = "0.0.0.0") -> ASGIApp:
    """Build the gated Starlette app serving the MCP server over Streamable HTTP."""
    from tp_mcp.server import server

    # Stateless + JSON responses: every POST is self-contained, so the server
    # survives restarts/scale-to-zero on hosted platforms without dangling sessions.
    starlette_app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        host=host,
        custom_starlette_routes=[Route(HEALTH_PATH, _health, methods=["GET"])],
    )
    return SecretGate(starlette_app, token)


def run_http_server(host: str, port: int) -> int:
    """Run the HTTP server (entry point for ``tp-mcp serve --http``)."""
    import asyncio

    from tp_mcp.server import _validate_auth_on_startup

    try:
        token = resolve_token(host)
    except ValueError as e:
        logger.error("%s", e)
        return 1

    if os.environ.get("TP_MCP_SKIP_STARTUP_VALIDATION") != "1":
        asyncio.run(_validate_auth_on_startup())

    logger.info("Starting TrainingPeaks MCP Server (Streamable HTTP) on %s:%d", host, port)
    if token:
        logger.info("Connector URL: https://<your-host>/<%s>%s", TOKEN_ENV_VAR, MCP_PATH)
    else:
        logger.warning("No %s set - endpoint is unauthenticated (loopback only).", TOKEN_ENV_VAR)

    # access_log=False: the secret-path URL would otherwise be written to the logs.
    uvicorn.run(build_app(token, host), host=host, port=port, log_level="info", proxy_headers=True, access_log=False)
    return 0
