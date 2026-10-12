from perp_farming_bots.security import Secrets


def test_secret_encryption_persists_without_plaintext(tmp_path):
    a = Secrets(tmp_path)
    encrypted = a.encrypt("not-a-real-token")
    assert "not-a-real-token" not in encrypted
    b = Secrets(tmp_path)
    assert b.decrypt(encrypted) == "not-a-real-token"
    assert not (tmp_path / "admin-password.txt").exists()
    assert (tmp_path / "encryption.key").stat().st_mode & 0o077 == 0
