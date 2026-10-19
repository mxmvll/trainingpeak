"""Vercel entrypoint - serves the connector over Streamable HTTP as a Vercel Function.

Vercel auto-detects a top-level ``app.py`` exposing an ASGI ``app``. Configure
TP_AUTH_COOKIE and TP_MCP_HTTP_TOKEN as project environment variables; the
connector URL is then ``https://<project>.vercel.app/<TP_MCP_HTTP_TOKEN>/mcp``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from tp_mcp.http_server import build_app, resolve_token  # noqa: E402

# Fail closed: a missing/weak token raises here, so the function never serves ungated.
app = build_app(resolve_token("0.0.0.0"))
