import pytest
from starlette.testclient import TestClient

from app.database.session import get_db


@pytest.mark.asyncio
async def test_websocket_sends_snapshot_then_answers_heartbeat(db_session, monkeypatch):
    import app.main as main_module

    async def _noop() -> None:
        return None

    monkeypatch.setattr(main_module, "init_db", _noop)
    monkeypatch.setattr(main_module.collector_manager, "start", _noop)
    monkeypatch.setattr(main_module.collector_manager, "stop", _noop)
    monkeypatch.setattr(main_module, "maybe_run_historical_backfill", _noop)

    async def _override_get_db():
        yield db_session

    main_module.app.dependency_overrides[get_db] = _override_get_db

    try:
        with TestClient(main_module.app) as client:
            with client.websocket_connect("/ws/market") as ws:
                snapshot = ws.receive_json()
                assert snapshot["type"] == "snapshot"
                assert "sources" in snapshot
                assert snapshot["quotes"] == []  # empty DB - honest, not fabricated

                ws.send_text("ping")
                assert ws.receive_text() == "pong"
    finally:
        main_module.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_websocket_disconnect_is_handled_cleanly(db_session, monkeypatch):
    import app.main as main_module

    async def _noop() -> None:
        return None

    monkeypatch.setattr(main_module, "init_db", _noop)
    monkeypatch.setattr(main_module.collector_manager, "start", _noop)
    monkeypatch.setattr(main_module.collector_manager, "stop", _noop)
    monkeypatch.setattr(main_module, "maybe_run_historical_backfill", _noop)

    async def _override_get_db():
        yield db_session

    main_module.app.dependency_overrides[get_db] = _override_get_db

    try:
        with TestClient(main_module.app) as client:
            with client.websocket_connect("/ws/market") as ws:
                ws.receive_json()  # snapshot
            # Exiting the `with` block closes the socket - the server must not
            # raise or hang; a second connection must still work afterwards.
            with client.websocket_connect("/ws/market") as ws2:
                second_snapshot = ws2.receive_json()
                assert second_snapshot["type"] == "snapshot"
    finally:
        main_module.app.dependency_overrides.clear()
