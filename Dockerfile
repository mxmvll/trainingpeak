# Hosted (remote) TrainingPeaks MCP connector - Streamable HTTP transport.
#
# Required runtime secrets (inject via your platform's secret store, never bake them in):
#   TP_AUTH_COOKIE     - your Production_tpAuth cookie value
#   TP_MCP_HTTP_TOKEN  - shared secret gating the endpoint (>= 32 chars, [A-Za-z0-9_-])
#
# Connector URL: https://<your-host>/<TP_MCP_HTTP_TOKEN>/mcp
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TP_MCP_HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 tpmcp

USER tpmcp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"

CMD ["tp-mcp", "serve", "--http"]
