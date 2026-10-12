from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet


def private_file(path: Path, value: bytes) -> bytes:
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
    os.chmod(path, 0o600)
    return path.read_bytes()


class Secrets:
    """Local encryption for saved notification tokens; application authentication is pending."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.cipher = Fernet(private_file(directory / "encryption.key", Fernet.generate_key()).strip())

    def encrypt(self, value: str) -> str:
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self.cipher.decrypt(value.encode()).decode()
