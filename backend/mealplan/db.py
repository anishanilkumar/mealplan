"""SQLite storage, and the change feed the PWA and Friday sync against.

The same model as Recipie's (see its db.py): every row has a `rev` counting
its edits and a global `seq`; a client pushes edits with the rev they were
based on and pulls everything after its cursor; deletes are tombstones. Every
write takes SQLite's write lock up front (`BEGIN IMMEDIATE`), so the web app
and the MCP server can't hand out the same seq.

One table holds every kind of row, so there is one feed and one cursor:
cooks, items and settings, which clients write, and the copy of Recipie's
recipes (kind `recipe`), which only recipes.py writes.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS rows (
    kind        TEXT NOT NULL,
    id          TEXT NOT NULL,
    rev         INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    deleted     INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT '',
    doc         TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE INDEX IF NOT EXISTS rows_seq ON rows(seq);

-- Where the copy of Recipie's recipes has got to in Recipie's own feed.
CREATE TABLE IF NOT EXISTS kv (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS login_states (
    state         TEXT PRIMARY KEY,
    verifier      TEXT NOT NULL,
    nonce         TEXT NOT NULL,
    created_at    REAL NOT NULL,
    app_challenge TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS app_handoffs (
    code_hash   TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    challenge   TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""


class Conflict(Exception):
    def __init__(self, current: dict):
        super().__init__("row changed since it was read")
        self.current = current


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or settings().db_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def closing(conn: sqlite3.Connection):
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write_tx(path: str | None = None):
    with closing(connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def init(path: str | None = None) -> None:
    with closing(connect(path)) as conn:
        conn.executescript(SCHEMA)


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    return {
        "kind": r["kind"],
        "id": r["id"],
        "rev": r["rev"],
        "seq": r["seq"],
        "deleted": bool(r["deleted"]),
        "updated_at": r["updated_at"],
        "updated_by": r["updated_by"],
        "doc": json.loads(r["doc"]),
    }


def _next_seq(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM rows").fetchone()[0]


def _select(conn: sqlite3.Connection, kind: str, row_id: str) -> dict | None:
    return _row(conn.execute("SELECT * FROM rows WHERE kind = ? AND id = ?", (kind, row_id)).fetchone())


# --- reads -------------------------------------------------------------------

def get(kind: str, row_id: str, *, include_deleted: bool = False) -> dict | None:
    with closing(connect()) as conn:
        r = _select(conn, kind, row_id)
    if r and r["deleted"] and not include_deleted:
        return None
    return r


def list_live(kind: str) -> list[dict]:
    with closing(connect()) as conn:
        rows = conn.execute("SELECT * FROM rows WHERE kind = ? AND deleted = 0", (kind,)).fetchall()
    return [_row(r) for r in rows]


def changes_since(seq: int, limit: int = 500) -> tuple[list[dict], int, bool]:
    """Rows changed after `seq`, the cursor to resume from, and whether more remain."""
    with closing(connect()) as conn:
        head = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM rows").fetchone()[0]
        # A cursor ahead of the server: the database was restored from an
        # older backup. Start the client again from the beginning.
        if seq > head:
            seq = 0
        rows = conn.execute(
            "SELECT * FROM rows WHERE seq > ? ORDER BY seq LIMIT ?", (seq, limit + 1)
        ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    cursor = rows[-1]["seq"] if more else max(head, seq)
    return [_row(r) for r in rows], cursor, more


def get_kv(key: str) -> str | None:
    with closing(connect()) as conn:
        r = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def set_kv(key: str, value: str) -> None:
    with write_tx() as conn:
        conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, value))


# --- writes ------------------------------------------------------------------

def save(kind: str, row_id: str, doc: dict, *, base_rev: int | None = None, user: str = "",
         conn: sqlite3.Connection | None = None) -> dict:
    """Create or replace a row.

    `base_rev=None` overwrites unconditionally; an integer is a
    compare-and-set (0 means "this is new"), raising Conflict on a mismatch.
    The doc must already be validated by the caller.
    """
    if conn is None:
        with write_tx() as c:
            return save(kind, row_id, doc, base_rev=base_rev, user=user, conn=c)
    current = _select(conn, kind, row_id)
    current_rev = current["rev"] if current else 0
    if base_rev is not None and base_rev != current_rev:
        raise Conflict(current)
    conn.execute(
        """INSERT INTO rows (kind, id, rev, seq, deleted, updated_at, updated_by, doc)
           VALUES (?, ?, ?, ?, 0, ?, ?, ?)
           ON CONFLICT(kind, id) DO UPDATE SET rev = excluded.rev, seq = excluded.seq,
             deleted = 0, updated_at = excluded.updated_at,
             updated_by = excluded.updated_by, doc = excluded.doc""",
        (kind, row_id, current_rev + 1, _next_seq(conn), now_iso(), user, json.dumps(doc)),
    )
    return _select(conn, kind, row_id)


def delete(kind: str, row_id: str, *, base_rev: int | None = None, user: str = "",
           conn: sqlite3.Connection | None = None) -> dict | None:
    """Tombstone a row. The document is kept."""
    if conn is None:
        with write_tx() as c:
            return delete(kind, row_id, base_rev=base_rev, user=user, conn=c)
    current = _select(conn, kind, row_id)
    if current is None:
        return None
    if base_rev is not None and base_rev != current["rev"]:
        raise Conflict(current)
    if current["deleted"]:
        return current
    conn.execute(
        "UPDATE rows SET rev = rev + 1, seq = ?, deleted = 1, updated_at = ?, updated_by = ? WHERE kind = ? AND id = ?",
        (_next_seq(conn), now_iso(), user, kind, row_id),
    )
    return _select(conn, kind, row_id)


# --- sessions (as Recipie's) -------------------------------------------------

def put_login_state(state: str, verifier: str, nonce: str, app_challenge: str = "") -> None:
    with write_tx() as conn:
        conn.execute("DELETE FROM login_states WHERE created_at < ?", (time.time() - 600,))
        conn.execute(
            "INSERT INTO login_states (state, verifier, nonce, created_at, app_challenge) VALUES (?, ?, ?, ?, ?)",
            (state, verifier, nonce, time.time(), app_challenge),
        )


def pop_login_state(state: str) -> dict | None:
    with write_tx() as conn:
        r = conn.execute(
            "SELECT * FROM login_states WHERE state = ? AND created_at >= ?",
            (state, time.time() - 600),
        ).fetchone()
        conn.execute("DELETE FROM login_states WHERE state = ?", (state,))
    return dict(r) if r else None


HANDOFF_SECONDS = 120


def put_app_handoff(code_hash: str, username: str, challenge: str) -> None:
    with write_tx() as conn:
        conn.execute("DELETE FROM app_handoffs WHERE created_at < ?", (time.time() - HANDOFF_SECONDS,))
        conn.execute(
            "INSERT INTO app_handoffs (code_hash, username, challenge, created_at) VALUES (?, ?, ?, ?)",
            (code_hash, username, challenge, time.time()),
        )


def pop_app_handoff(code_hash: str) -> dict | None:
    with write_tx() as conn:
        r = conn.execute(
            "SELECT * FROM app_handoffs WHERE code_hash = ? AND created_at >= ?",
            (code_hash, time.time() - HANDOFF_SECONDS),
        ).fetchone()
        conn.execute("DELETE FROM app_handoffs WHERE code_hash = ?", (code_hash,))
    return dict(r) if r else None


def create_session(token_hash: str, username: str, days: int) -> None:
    now = time.time()
    with write_tx() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, username, now, now + days * 86400),
        )


def session_user(token_hash: str, days: int) -> str | None:
    now = time.time()
    with closing(connect()) as conn:
        r = conn.execute(
            "SELECT username, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if r is None or r["expires_at"] < now:
            return None
        if r["expires_at"] < now + (days - 1) * 86400:
            conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (now + days * 86400, token_hash))
        return r["username"]


def drop_session(token_hash: str) -> None:
    with write_tx() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
