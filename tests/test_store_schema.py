"""Unsupported prerelease formats must not be silently converted."""

import sqlite3

import pytest

from perp_farming_bots.store import Store


@pytest.mark.parametrize("version", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11])
def test_unsupported_database_is_rejected_without_rewriting_any_rows(tmp_path, version):
    path = tmp_path / "unsupported.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE evidence (value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('preserve')")
        db.execute(f"PRAGMA user_version={version}")
    with pytest.raises(ValueError, match="schema version"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == version
        assert db.execute("SELECT value FROM evidence").fetchall() == [("preserve",)]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("evidence",)]


def test_new_database_uses_current_format_and_reopens_without_conversion(tmp_path):
    path = tmp_path / "current.db"
    store = Store(path)
    store.close()
    reopened = Store(path)
    try:
        with reopened.engine.connect() as db:
            assert db.exec_driver_sql("PRAGMA user_version").scalar_one() == 10
        assert reopened.bots() == []
    finally:
        reopened.close()
