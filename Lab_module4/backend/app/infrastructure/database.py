import sqlite3
from pathlib import Path

# Constant DDL — the only statements run through executescript (never built from input).
SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS codebases (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    data_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    codebase    TEXT NOT NULL,
    path        TEXT NOT NULL,
    data_json   TEXT NOT NULL,
    PRIMARY KEY (codebase, path)
);
CREATE TABLE IF NOT EXISTS embedding_cache (
    model       TEXT NOT NULL,
    key         TEXT NOT NULL,
    vector      BLOB NOT NULL,
    PRIMARY KEY (model, key)
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key           TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    data_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traces (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    data_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    data_json   TEXT NOT NULL
);
"""


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init(path: str) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
