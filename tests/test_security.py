import base64

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from perp_farming_bots.security import BasicAuth, Secrets


def client():
    app = FastAPI()
    app.add_middleware(BasicAuth, password="a-long-test-password")

    @app.get("/api/private")
    def private():
        return {"protected": True}

    @app.post("/api/control")
    def control():
        return {"accepted": True}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        await ws.accept()
        await ws.send_text("authorized")
        await ws.close()

    return TestClient(app)


def authorization():
    return {"Authorization": "Basic " + base64.b64encode(b"admin:a-long-test-password").decode()}


def test_http_and_cross_origin_controls():
    with client() as c:
        assert c.get("/api/private").status_code == 401
        assert c.get("/api/private", headers=authorization()).status_code == 200
        assert (
            c.post(
                "/api/control", headers={**authorization(), "Origin": "https://attacker.example"}
            ).status_code
            == 401
        )
        assert (
            c.post("/api/control", headers={**authorization(), "Origin": "http://testserver"}).status_code
            == 200
        )


def test_websocket_authentication_and_origin():
    with client() as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws"):
                pass
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(
                "/ws", headers={**authorization(), "Origin": "https://attacker.example"}
            ):
                pass
        with c.websocket_connect("/ws", headers={**authorization(), "Origin": "http://testserver"}) as ws:
            assert ws.receive_text() == "authorized"


def test_secret_encryption_persists_without_plaintext(tmp_path):
    a = Secrets(tmp_path)
    encrypted = a.encrypt("not-a-real-token")
    assert "not-a-real-token" not in encrypted
    b = Secrets(tmp_path)
    assert b.decrypt(encrypted) == "not-a-real-token"
    assert b.password == a.password
    assert (tmp_path / "encryption.key").stat().st_mode & 0o077 == 0


def test_invalid_existing_password_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("PFB_ADMIN_PASSWORD", raising=False)
    (tmp_path / "admin-password.txt").write_text("")
    with pytest.raises(ValueError, match="密码文件无效"):
        Secrets(tmp_path)
