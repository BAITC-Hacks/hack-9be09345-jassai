from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('revision', '0');
CREATE TABLE IF NOT EXISTS entities(
    kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY(kind,id)
);
CREATE TABLE IF NOT EXISTS users(
    username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('hr','employee')),
    employee_id TEXT UNIQUE,
    CHECK((role='hr' AND employee_id IS NULL) OR (role='employee' AND employee_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS sessions(
    token_hash TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username),
    csrf_token TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_limits(
    client TEXT PRIMARY KEY, failures INTEGER NOT NULL, started_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS import_batches(
    id TEXT PRIMARY KEY, username TEXT NOT NULL, base_revision INTEGER NOT NULL,
    payload TEXT NOT NULL, report TEXT NOT NULL, applied INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency(
    username TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL,
    response TEXT NOT NULL, PRIMARY KEY(username,key)
);
CREATE TABLE IF NOT EXISTS recommendation_cache(
    context_hash TEXT PRIMARY KEY, response TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gamification_preferences(
    employee_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    quest_event_id TEXT,
    quest_state TEXT CHECK(quest_state IN ('active','completed')),
    quest_completed_at TEXT
);
CREATE TABLE IF NOT EXISTS gamification_rewards(
    record_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    xp INTEGER NOT NULL CHECK(xp>0),
    gained_levels INTEGER NOT NULL CHECK(gained_levels>0),
    quest_completed INTEGER NOT NULL DEFAULT 0 CHECK(quest_completed IN (0,1)),
    earned_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS gamification_rewards_employee ON gamification_rewards(employee_id,earned_at);
CREATE TABLE IF NOT EXISTS companion_equipment(
    employee_id TEXT NOT NULL,
    slot TEXT NOT NULL CHECK(slot IN ('head','body','accessory','background')),
    item_id TEXT NOT NULL,
    PRIMARY KEY(employee_id,slot)
);
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    @contextmanager
    def connection(self, write=False):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def revision(conn):
    return int(get_meta(conn, "revision", "0"))


def bump_revision(conn):
    set_meta(conn, "revision", revision(conn) + 1)
    conn.execute("DELETE FROM recommendation_cache")


def all_entities(conn, kind):
    return {row["id"]: json.loads(row["data"]) for row in conn.execute("SELECT id,data FROM entities WHERE kind=? ORDER BY id", (kind,))}


def get_entity(conn, kind, entity_id):
    row = conn.execute("SELECT data FROM entities WHERE kind=? AND id=?", (kind, entity_id)).fetchone()
    return json.loads(row[0]) if row else None


def put_entity(conn, kind, entity_id, data):
    conn.execute("INSERT INTO entities VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data", (kind, entity_id, encode(data)))


def snapshot(conn):
    return {kind: all_entities(conn, kind) for kind in ("employees", "skills", "role_profiles", "events", "history")}
