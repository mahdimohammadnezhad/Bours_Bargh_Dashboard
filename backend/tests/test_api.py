import pytest

from app.core.rate_limit import RateLimitMiddleware


@pytest.mark.asyncio
async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_health_live(client):
    resp = await client.get("/api/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_sources_lists_all_three_collectors(client):
    resp = await client.get("/api/health/sources")
    assert resp.status_code == 200
    body = resp.json()
    source_ids = {s["source_id"] for s in body}
    assert source_ids == {"tsetmc", "iee_new", "iee_old"}


@pytest.mark.asyncio
async def test_iee_old_collector_reports_not_configured(client):
    # iee_new became a real, verified collector (see docs/DATA_SOURCES.md /
    # iee_new_collector.py) - only iee_old is still an unimplemented stub.
    resp = await client.get("/api/health/sources")
    body = {s["source_id"]: s for s in resp.json()}
    assert body["iee_old"]["status"] == "not_configured"
    assert body["iee_new"]["status"] != "not_configured"


@pytest.mark.asyncio
async def test_market_status(client):
    resp = await client.get("/api/market/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "is_active_session" in body
    assert len(body["sources"]) == 3


@pytest.mark.asyncio
async def test_market_quotes_empty_db_returns_empty_list(client):
    resp = await client.get("/api/market/quotes")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_analytics_overview_reports_insufficient_data_on_empty_db(client):
    resp = await client.get(
        "/api/analytics/overview", params={"source_id": "tsetmc", "symbol": "IR-ELEC-001"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "insufficient_data"
    assert body["available_points"] == 0


@pytest.mark.asyncio
async def test_analytics_anomalies_reports_insufficient_data_on_empty_db(client):
    resp = await client.get(
        "/api/analytics/anomalies", params={"source_id": "tsetmc", "symbol": "IR-ELEC-001"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "insufficient_data"
    assert body["anomalies"] == []


@pytest.mark.asyncio
async def test_history_prices_empty_range(client):
    resp = await client.get("/api/history/prices", params={"source_id": "tsetmc", "symbol": "IR-ELEC-001"})
    assert resp.status_code == 200
    assert resp.json()["points"] == []


def _rate_limited_app(requests_per_minute: int):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route, WebSocketRoute

    async def ok(request):
        return PlainTextResponse("ok")

    async def ws_ok(websocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    app = Starlette(routes=[Route("/thing", ok), WebSocketRoute("/ws/thing", ws_ok)])
    app.add_middleware(RateLimitMiddleware, requests_per_minute=requests_per_minute)
    return app


class TestRateLimitMiddleware:
    def test_allows_requests_under_the_limit(self):
        from starlette.testclient import TestClient

        client = TestClient(_rate_limited_app(requests_per_minute=3))
        for _ in range(3):
            assert client.get("/thing").status_code == 200

    def test_blocks_requests_over_the_limit_with_429_and_retry_after(self):
        from starlette.testclient import TestClient

        client = TestClient(_rate_limited_app(requests_per_minute=2))
        assert client.get("/thing").status_code == 200
        assert client.get("/thing").status_code == 200
        resp = client.get("/thing")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_websocket_paths_are_exempt_from_the_limit(self):
        from starlette.testclient import TestClient

        client = TestClient(_rate_limited_app(requests_per_minute=1))
        # Burn the one allowed HTTP request so the limit is now exhausted.
        assert client.get("/thing").status_code == 200
        assert client.get("/thing").status_code == 429
        # The WebSocket route must still connect - it's on the exempt prefix.
        with client.websocket_connect("/ws/thing") as ws:
            assert ws.receive_text() == "hi"

    def test_zero_disables_rate_limiting(self):
        from starlette.testclient import TestClient

        client = TestClient(_rate_limited_app(requests_per_minute=0))
        for _ in range(10):
            assert client.get("/thing").status_code == 200
