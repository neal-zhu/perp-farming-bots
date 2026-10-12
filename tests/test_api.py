import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from perp_farming_bots.api import register_routes
from perp_farming_bots.markets import Markets
from perp_farming_bots.notifications import Notifications
from perp_farming_bots.runtime import Runtime
from perp_farming_bots.security import BasicAuth, Secrets
from perp_farming_bots.store import Store


def test_authenticated_api_flow_and_same_venue_bindings(tmp_path: Path):
    store = Store(tmp_path / "api.db")
    secrets = Secrets(tmp_path)
    runtime = Runtime(store, Markets())
    notifications = Notifications(store, secrets)
    app = FastAPI()
    app.add_middleware(BasicAuth, password=secrets.password)
    register_routes(app, store, runtime, notifications)
    with TestClient(app) as client:
        assert client.get("/api/connections").status_code == 401
        client.auth = ("admin", secrets.password)
        account_a = client.post(
            "/api/connections", json={"name": "同场馆 A", "provider": "demo_a", "account_ref": "A"}
        ).json()
        account_b = client.post(
            "/api/connections", json={"name": "同场馆 B", "provider": "demo_a", "account_ref": "B"}
        ).json()
        body = {
            "request_id": "stable-request-id",
            "name": "同场馆对冲",
            "parameters": {
                "long_connection_id": account_a["id"],
                "short_connection_id": account_b["id"],
                "symbol": "BTC",
                "threshold_pct": "-0.1",
                "target_usd": "1000",
            },
        }
        first = client.post("/api/bots", json=body)
        assert first.status_code == 201
        assert client.post("/api/bots", json=body).json()["id"] == first.json()["id"]
        bot_id = first.json()["id"]
        assert client.post(f"/api/bots/{bot_id}/commands", json={"action": "start"}).status_code == 200
        assert client.post("/api/bots", json={**body, "execution": "live"}).status_code == 422
        assert client.get("/api/catalog").json()["live_trading"] is False
        assert client.get("/api/points").json()[0]["value"] is None
        assert client.delete(f"/api/connections/{account_a['id']}").status_code == 400
        assert (
            client.post(f"/api/bots/{bot_id}/commands", json={"action": "stop"}).json()["state"] == "stopped"
        )
    asyncio.run(notifications.stop())
    store.close()
