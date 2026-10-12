from conftest import FixtureAccounts, FixtureMarkets, connection_value
from fastapi import FastAPI
from fastapi.testclient import TestClient

from perp_farming_bots.api import register_routes
from perp_farming_bots.notifications import Notifications
from perp_farming_bots.runtime import Runtime
from perp_farming_bots.security import Secrets
from perp_farming_bots.store import Store


def test_native_account_api_has_no_virtual_funds_or_exposed_keys(tmp_path):
    store = Store(tmp_path / "api.db")
    secrets = Secrets(tmp_path)
    markets = FixtureMarkets()
    accounts = FixtureAccounts(store, markets, secrets)
    runtime = Runtime(store, markets, accounts)
    notifications = Notifications(store, secrets)
    app = FastAPI()
    register_routes(app, store, runtime, notifications)
    with TestClient(app) as client:
        assert client.get("/api/connections").json() == []
        assert client.get("/api/catalog").json()["execution"] == "native"
        assert all(
            p["id"] not in {"demo_a", "demo_b"} for p in client.get("/api/catalog").json()["providers"]
        )
        value = connection_value().model_dump(mode="json")
        value["api_private_key"] = "22" * 32
        account = client.post("/api/connections", json=value)
        assert account.status_code == 201
        assert "api_private_key" not in account.json()
        assert "credentials" not in account.json()
        assert "paper_balance" not in account.json()
        listing = client.get("/api/connections").json()
        assert listing[0]["snapshot"]["available"] == "10000"
        assert listing[0]["account_ref"].endswith(":0")
        assert client.get("/api/points").json()[0]["metrics"][0]["value"] is None
        assert client.post("/api/connections", json={**value, "paper_balance": "10000"}).status_code == 422
        assert client.post("/api/connections", json={**value, "provider": "demo_a"}).status_code == 422
        invalid = client.post("/api/connections", json={**value, "account_index": 10})
        assert invalid.status_code == 422
        assert value["api_private_key"] not in invalid.text
    import asyncio

    asyncio.run(markets.close())
    store.close()
