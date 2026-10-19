"""Tests for the Streamable HTTP transport (``tp-mcp serve --http``)."""

import pytest
from starlette.testclient import TestClient

from tp_mcp.http_server import TOKEN_ENV_VAR, build_app, resolve_token
from tp_mcp.server import TOOLS

TOKEN = "a" * 20 + "B-_" + "c" * 20

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-06-18",
}

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "http-test", "version": "0"},
    },
}

TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


@pytest.fixture
def client():
    with TestClient(build_app(TOKEN, host="0.0.0.0"), base_url="https://tp.example.com") as c:
        yield c


class TestResolveToken:
    def test_required_on_public_host(self, monkeypatch):
        monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
        with pytest.raises(ValueError, match=TOKEN_ENV_VAR):
            resolve_token("0.0.0.0")

    def test_optional_on_loopback(self, monkeypatch):
        monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
        assert resolve_token("127.0.0.1") is None

    def test_too_short_rejected(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV_VAR, "short")
        with pytest.raises(ValueError, match="at least"):
            resolve_token("0.0.0.0")

    def test_url_unsafe_chars_rejected(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV_VAR, "x" * 40 + "/?")
        with pytest.raises(ValueError, match="letters"):
            resolve_token("0.0.0.0")

    def test_valid_token(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV_VAR, TOKEN)
        assert resolve_token("0.0.0.0") == TOKEN


class TestGate:
    def test_health_is_open(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_bare_mcp_without_token_is_hidden(self, client):
        r = client.post("/mcp", json=INITIALIZE, headers=HEADERS)
        assert r.status_code == 404

    def test_wrong_secret_path_is_hidden(self, client):
        r = client.post("/" + "z" * len(TOKEN) + "/mcp", json=INITIALIZE, headers=HEADERS)
        assert r.status_code == 404

    def test_wrong_bearer_is_hidden(self, client):
        r = client.post("/mcp", json=INITIALIZE, headers={**HEADERS, "Authorization": "Bearer nope"})
        assert r.status_code == 404

    def test_secret_path_does_not_expose_other_routes_by_prefix(self, client):
        r = client.post(f"/{TOKEN}x/mcp", json=INITIALIZE, headers=HEADERS)
        assert r.status_code == 404


class TestProtocolOverHttp:
    def _assert_handshake(self, client, path, extra_headers=None):
        headers = {**HEADERS, **(extra_headers or {})}
        init = client.post(path, json=INITIALIZE, headers=headers)
        assert init.status_code == 200, init.text
        assert init.json()["result"]["serverInfo"]["name"] == "trainingpeaks-mcp"

        tools = client.post(path, json=TOOLS_LIST, headers=headers)
        assert tools.status_code == 200, tools.text
        assert len(tools.json()["result"]["tools"]) == len(TOOLS)

    def test_secret_path(self, client):
        self._assert_handshake(client, f"/{TOKEN}/mcp")

    def test_bearer_header(self, client):
        self._assert_handshake(client, "/mcp", {"Authorization": f"Bearer {TOKEN}"})

    def test_no_token_on_loopback(self):
        with TestClient(build_app(None, host="127.0.0.1"), base_url="http://127.0.0.1:8000") as c:
            self._assert_handshake(c, "/mcp")
