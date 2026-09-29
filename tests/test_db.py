import sqlite3
from pathlib import Path

import pytest

from shop_platform.db import Database
from shop_platform.ids import new_id


def _write(dir: Path, name: str, sql: str) -> None:
    (dir / name).write_text(sql)


def test_migrations_apply_once_in_order(tmp_path: Path) -> None:
    _write(tmp_path, "001_items.sql", "CREATE TABLE items (id TEXT PRIMARY KEY);")
    _write(tmp_path, "002_price.sql", "ALTER TABLE items ADD COLUMN price INTEGER;")
    db = Database(":memory:")

    assert db.migrate(tmp_path) == ["001_items.sql", "002_price.sql"]
    assert db.migrate(tmp_path) == []
    with db.transaction() as conn:
        conn.execute("INSERT INTO items (id, price) VALUES ('a', 1)")


def test_failed_migration_leaves_nothing_behind(tmp_path: Path) -> None:
    _write(tmp_path, "001_bad.sql", "CREATE TABLE ok (id TEXT); CREATE TABLE broken (;")
    db = Database(":memory:")
    with pytest.raises(sqlite3.Error):
        db.migrate(tmp_path)
    with db.read() as conn:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "ok" not in tables


def test_transaction_rolls_back_on_error() -> None:
    db = Database(":memory:")
    with db.transaction() as conn:
        conn.execute("CREATE TABLE t (v INTEGER)")
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_new_id_has_prefix() -> None:
    assert new_id("ord").startswith("ord_")
    with pytest.raises(ValueError):
        new_id("Order")
