"""SQLite schema migrations for the job registry.

`PRAGMA user_version` records the schema version. Every migration runs once, inside a transaction,
after an online backup of the database (sqlite3 backup API) to .pipeline/backups/. v0.2.0 databases
are version 0/1 and are upgraded in place; existing jobs, stages and events are untouched."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .paths import STATE_DIR

BACKUP_DIR = STATE_DIR / "backups"

MIGRATIONS: dict[int, str] = {
    # v1: the v0.2.0 schema (jobs, stages, events, render_slots) — created by jobs.SCHEMA
    1: "",
    # v2: v0.3.0 production lifecycle, approvals, review flags, publications, scheduler, audit log
    2: """
CREATE TABLE IF NOT EXISTS productions (
  id TEXT PRIMARY KEY, brand TEXT NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL,
  brief_json TEXT, concepts_path TEXT, concept_id TEXT, storyboard_path TEXT, project_path TEXT,
  job_id TEXT, dir TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS productions_state ON productions(state);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, production_id TEXT NOT NULL, package_hash TEXT NOT NULL,
  decision TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT, created_at REAL NOT NULL,
  invalidated_at REAL, invalidated_reason TEXT
);
CREATE INDEX IF NOT EXISTS approvals_prod ON approvals(production_id);
CREATE TABLE IF NOT EXISTS review_flags (
  id INTEGER PRIMARY KEY AUTOINCREMENT, production_id TEXT NOT NULL, kind TEXT NOT NULL,
  severity TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  source TEXT, created_at REAL NOT NULL, resolved_by TEXT, resolved_at REAL, resolution_note TEXT,
  UNIQUE(production_id, kind, message)
);
CREATE TABLE IF NOT EXISTS publications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, production_id TEXT NOT NULL, platform TEXT NOT NULL,
  status TEXT NOT NULL, approval_id INTEGER, content_hash TEXT NOT NULL, remote_id TEXT,
  created_at REAL NOT NULL, finished_at REAL, error TEXT
);
CREATE TABLE IF NOT EXISTS sched_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, priority INTEGER NOT NULL, pid INTEGER,
  job_ref TEXT, state TEXT NOT NULL, enqueued_at REAL NOT NULL, granted_at REAL, heartbeat REAL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  subject TEXT, detail_json TEXT
);
""",
    # v3: archiving (hidden from lists and the dashboard; files moved to output/_archive/, audit history kept)
    3: """
ALTER TABLE productions ADD COLUMN archived_at REAL;
ALTER TABLE jobs ADD COLUMN archived_at REAL
""",
}
LATEST = max(MIGRATIONS)


def backup(db: Path, label: str, backup_dir: Path | None = None) -> Path | None:
    if not db.exists() or db.stat().st_size == 0:
        return None
    # backups live next to the database they protect (a test DB never writes into the real backups)
    d = backup_dir or (BACKUP_DIR if db.parent.resolve() == STATE_DIR.resolve() else db.parent / "backups")
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"{db.stem}-{label}-{time.strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(db)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def stamp_fresh(db: Path) -> None:
    """A database created by this version is already at LATEST: never treat it as a v0.2.0 database."""
    c = sqlite3.connect(db, timeout=30, isolation_level=None)
    try:
        for v in range(1, LATEST + 1):
            for stmt in [x for x in MIGRATIONS[v].split(";") if x.strip()]:
                c.execute(stmt)
        c.execute(f"PRAGMA user_version={LATEST}")
    finally:
        c.close()


def migrate(db: Path) -> dict:
    """Bring `db` to LATEST. Returns {from, to, backup}."""
    c = sqlite3.connect(db, timeout=30, isolation_level=None)
    try:
        cur = c.execute("PRAGMA user_version").fetchone()[0]
        has_jobs = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        if cur == 0 and has_jobs:
            cur = 1  # an unversioned v0.2.0 database
        if cur >= LATEST:
            if c.execute("PRAGMA user_version").fetchone()[0] != cur:
                c.execute(f"PRAGMA user_version={cur}")
            return {"from": cur, "to": cur, "backup": None}
    finally:
        c.close()
    bk = backup(db, f"pre-v{LATEST}", BACKUP_DIR if db.parent.resolve() == STATE_DIR.resolve() else None) if has_jobs else None
    c = sqlite3.connect(db, timeout=30, isolation_level=None)
    try:
        for v in range(cur + 1, LATEST + 1):
            c.execute("BEGIN IMMEDIATE")
            if MIGRATIONS[v]:
                for stmt in [s for s in MIGRATIONS[v].split(";") if s.strip()]:
                    c.execute(stmt)
            c.execute(f"PRAGMA user_version={v}")
            c.execute("COMMIT")
    finally:
        c.close()
    return {"from": cur, "to": LATEST, "backup": str(bk) if bk else None}
