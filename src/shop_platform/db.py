"""SQLite access shared by the services: one connection, serialized access, ordered migrations."""

import logging
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATION_NAME = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")


class Database:
    """Wraps a single SQLite connection.

    FastAPI runs plain `def` endpoints on a thread pool, so every use of the connection goes
    through ``read()`` or ``transaction()``, which hold a re-entrant lock.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run the block in one write transaction. Nested calls join the outer transaction."""
        with self._lock:
            if self._conn.in_transaction:
                yield self._conn
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def migrate(self, migrations_dir: Path) -> list[str]:
        """Apply ``NNN_name.sql`` files that have not run yet, in name order.

        Each file runs in its own transaction together with its bookkeeping row, so a
        failing file leaves no partial schema behind. Returns the names applied.
        """
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name TEXT PRIMARY KEY,"
                " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
            )
            done = {row["name"] for row in self._conn.execute("SELECT name FROM schema_migrations")}
            applied: list[str] = []
            for path in sorted(migrations_dir.glob("*.sql")):
                if path.name in done:
                    continue
                if not _MIGRATION_NAME.match(path.name):
                    raise ValueError(
                        f"migration file name must look like 001_name.sql: {path.name}"
                    )
                script = (
                    "BEGIN IMMEDIATE;\n"
                    f"{path.read_text()}\n"
                    f"INSERT INTO schema_migrations (name) VALUES ('{path.name}');\n"
                    "COMMIT;"
                )
                try:
                    self._conn.executescript(script)
                except sqlite3.Error:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    logger.exception("migration failed", extra={"migration": path.name})
                    raise
                logger.info("migration applied", extra={"migration": path.name})
                applied.append(path.name)
            return applied

    def close(self) -> None:
        with self._lock:
            self._conn.close()
