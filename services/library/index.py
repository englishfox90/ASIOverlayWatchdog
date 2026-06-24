"""
Image library SQLite index.

Stores one row per archived frame: capture time (PC local epoch), relative file
path, dimensions, byte size, and denormalised metadata for filtering/display
without opening the JPEG. A single connection is shared across threads
(``check_same_thread=False``) and guarded by a lock; WAL mode keeps the capture
worker's writes from blocking web-thread reads.
"""
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at  INTEGER NOT NULL,
    path         TEXT    NOT NULL,
    width        INTEGER,
    height       INTEGER,
    bytes        INTEGER NOT NULL,
    session      TEXT,
    exposure     TEXT,
    gain         TEXT,
    temp         TEXT,
    camera       TEXT,
    weather      TEXT,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_captured_at ON images(captured_at);
"""

# Columns surfaced in query results / accepted on insert (besides auto id).
_FIELDS = (
    "captured_at", "path", "width", "height", "bytes",
    "session", "exposure", "gain", "temp", "camera", "weather", "created_at",
)


class LibraryIndex:
    """Thread-safe SQLite wrapper for the image library."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def insert(self, record):
        """Insert one image row. ``record`` is a dict keyed by ``_FIELDS``.

        Returns the new row id.
        """
        cols = ", ".join(_FIELDS)
        placeholders = ", ".join("?" for _ in _FIELDS)
        values = [record.get(f) for f in _FIELDS]
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO images ({cols}) VALUES ({placeholders})", values
            )
            self._conn.commit()
            return cur.lastrowid

    def query(self, since=None, until=None, limit=100, offset=0):
        """Return rows (newest first) optionally bounded by a capture-time range."""
        where, params = self._range_clause(since, until)
        sql = f"SELECT id, {', '.join(_FIELDS)} FROM images{where} " \
              "ORDER BY captured_at DESC, id DESC LIMIT ? OFFSET ?"
        params = params + [int(limit), int(offset)]
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count(self, since=None, until=None):
        where, params = self._range_clause(since, until)
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM images{where}", params
            ).fetchone()
        return int(row["n"])

    def get(self, image_id):
        """Return a single row by id, or None."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT id, {', '.join(_FIELDS)} FROM images WHERE id = ?",
                [int(image_id)],
            ).fetchone()
        return dict(row) if row else None

    def total_bytes(self):
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(bytes), 0) AS total FROM images"
            ).fetchone()
        return int(row["total"])

    def rows_older_than(self, cutoff_epoch):
        """(id, path, bytes) for rows captured before ``cutoff_epoch``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, path, bytes FROM images WHERE captured_at < ? "
                "ORDER BY captured_at ASC, id ASC",
                [int(cutoff_epoch)],
            ).fetchall()
        return [(r["id"], r["path"], r["bytes"]) for r in rows]

    def oldest_rows(self, limit):
        """(id, path, bytes) for the oldest ``limit`` rows, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, path, bytes FROM images "
                "ORDER BY captured_at ASC, id ASC LIMIT ?",
                [int(limit)],
            ).fetchall()
        return [(r["id"], r["path"], r["bytes"]) for r in rows]

    def all_rows(self):
        """(id, path) for every row — used for orphan reconciliation."""
        with self._lock:
            rows = self._conn.execute("SELECT id, path FROM images").fetchall()
        return [(r["id"], r["path"]) for r in rows]

    def delete_ids(self, ids):
        """Delete rows by id. Returns the number removed."""
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM images WHERE id IN ({placeholders})", ids
            )
            self._conn.commit()
            return cur.rowcount

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    @staticmethod
    def _range_clause(since, until):
        clauses, params = [], []
        if since is not None:
            clauses.append("captured_at >= ?")
            params.append(int(since))
        if until is not None:
            clauses.append("captured_at <= ?")
            params.append(int(until))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params
