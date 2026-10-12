from __future__ import annotations

import base64
import hmac
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


def private_file(path: Path, value: bytes) -> bytes:
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
    os.chmod(path, 0o600)
    return path.read_bytes()


class Secrets:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.cipher = Fernet(private_file(directory / "encryption.key", Fernet.generate_key()).strip())
        provided = os.environ.get("PFB_ADMIN_PASSWORD")
        if provided is not None and len(provided) < 12:
            raise ValueError("PFB_ADMIN_PASSWORD 必须至少 12 个字符")
        self.password = (
            provided
            or private_file(directory / "admin-password.txt", secrets.token_urlsafe(24).encode())
            .decode()
            .strip()
        )
        if len(self.password) < 12:
            raise ValueError("管理员密码文件无效，必须至少 12 个字符")

    def encrypt(self, value: str) -> str:
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self.cipher.decrypt(value.encode()).decode()


class BasicAuth:
    """Protect both HTTP and websocket transports; reject cross-origin control requests."""

    def __init__(self, app, password: str):
        self.app = app
        self.password = password

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        if scope["type"] == "http" and scope.get("path") == "/health":
            return await self.app(scope, receive, send)
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        authorized = False
        try:
            scheme, token = headers.get("authorization", "").split(" ", 1)
            username, password = base64.b64decode(token, validate=True).decode().split(":", 1)
            authorized = scheme.lower() == "basic" and hmac.compare_digest(username, "admin")
            authorized = authorized and hmac.compare_digest(password.encode(), self.password.encode())
        except (ValueError, UnicodeError):
            pass
        origin = headers.get("origin")
        if origin is not None and (
            scope["type"] == "websocket" or scope.get("method") not in {"GET", "HEAD", "OPTIONS"}
        ):
            parsed = urlsplit(origin)
            authorized = (
                authorized
                and parsed.netloc == headers.get("host")
                and parsed.scheme
                in {
                    scope["scheme"],
                    "http"
                    if scope["scheme"] == "ws"
                    else "https"
                    if scope["scheme"] == "wss"
                    else scope["scheme"],
                }
            )
        if authorized:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"www-authenticate", b'Basic realm="Perp Farming Bots"'),
                    (b"content-type", b"text/plain; charset=utf-8"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"Authentication required"})
