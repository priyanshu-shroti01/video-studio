"""Persistent job registry (SQLite, WAL) with a validated state machine, per-stage records,
heartbeats for crash/stale detection, cancellation flags and duplicate-job prevention."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import DuplicateJob, NotFound, StateError
from .paths import STATE_DIR, ensure_dirs

STAGES = ["PREPARING", "GENERATING_AUDIO", "BUILDING_TIMELINE", "RENDERING", "POST_PROCESSING", "QA"]
ACTIVE = set(STAGES) | {"RETRYING"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
STATES = {"QUEUED", *STAGES, "COMPLETED", "FAILED", "CANCELLED", "RETRYING"}

_NEXT = {s: STAGES[i + 1] for i, s in enumerate(STAGES[:-1])}
TRANSITIONS: dict[str, set[str]] = {
    "QUEUED": {"PREPARING", "CANCELLED"},
    **{s: {_NEXT.get(s, "COMPLETED"), "FAILED", "CANCELLED"} for s in STAGES},
    "RETRYING": {"PREPARING", "FAILED", "CANCELLED"},
    "FAILED": {"RETRYING"},
    "CANCELLED": {"RETRYING"},
    "COMPLETED": set(),
}
STALE_AFTER_S = 120  # no heartbeat for this long while "active" => the worker died

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL, state TEXT NOT NULL,
  stage TEXT, progress REAL DEFAULT 0, message TEXT, config_json TEXT NOT NULL, config_path TEXT,
  output_dir TEXT NOT NULL, created_at REAL NOT NULL, started_at REAL, updated_at REAL NOT NULL,
  completed_at REAL, heartbeat REAL, pid INTEGER, attempts INTEGER DEFAULT 0,
  cancel_requested INTEGER DEFAULT 0, error_json TEXT, qa_status TEXT
);
CREATE INDEX IF NOT EXISTS jobs_key ON jobs(key_hash);
CREATE TABLE IF NOT EXISTS stages (
  job_id TEXT NOT NULL, stage TEXT NOT NULL, input_hash TEXT, status TEXT NOT NULL,
  started_at REAL, finished_at REAL, seconds REAL, outputs_json TEXT, error_json TEXT,
  PRIMARY KEY (job_id, stage)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, ts REAL, level TEXT, stage TEXT, message TEXT, data_json TEXT
);
CREATE TABLE IF NOT EXISTS render_slots (
  slot INTEGER PRIMARY KEY, job_id TEXT, pid INTEGER, acquired_at REAL, heartbeat REAL
);
"""


def db_path() -> Path:
    return Path(os.environ.get("VIDEO_PIPELINE_DB", STATE_DIR / "registry.db"))


class Registry:
    def __init__(self, path: Path | None = None):
        ensure_dirs()
        self.path = path or db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists() and self.path.stat().st_size > 0
        with self.conn() as c:
            c.executescript(SCHEMA)
        from .migrations import migrate, stamp_fresh
        if not existed:
            stamp_fresh(self.path)
        self.migration = migrate(self.path)

    def audit(self, actor: str, action: str, subject: str | None = None, detail: dict | None = None) -> None:
        """Append-only audit trail for human decisions and outward-facing actions."""
        with self.conn() as c:
            c.execute("INSERT INTO audit_log (ts, actor, action, subject, detail_json) VALUES (?,?,?,?,?)",
                      (time.time(), actor, action, subject, json.dumps(detail) if detail else None))

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
        finally:
            c.close()

    # ---- jobs ---------------------------------------------------------------------------
    def create(self, name: str, key_hash: str, config: dict, config_path: str | None, output_root: Path,
               *, force: bool = False) -> dict:
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            dup = c.execute("SELECT id, state FROM jobs WHERE key_hash=? AND archived_at IS NULL AND state NOT IN ('FAILED','CANCELLED') "
                            "ORDER BY created_at DESC LIMIT 1", (key_hash,)).fetchone()
            if dup and not force:
                c.execute("ROLLBACK")
                raise DuplicateJob(f"an identical job already exists: {dup['id']} ({dup['state']})",
                                   detail="use `retry`/`render` on that job, or `create --force` for a new copy")
            jid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            now = time.time()
            out = output_root / jid
            c.execute("INSERT INTO jobs (id,name,key_hash,state,config_json,config_path,output_dir,created_at,updated_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?)",
                      (jid, name, key_hash, "QUEUED", json.dumps(config), config_path, str(out), now, now))
            c.execute("COMMIT")
        self.event(jid, "info", None, "job created")
        return self.get(jid)

    def get(self, jid: str) -> dict:
        with self.conn() as c:
            r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not r:
            raise NotFound(f"no job {jid!r}")
        d = dict(r)
        d["config"] = json.loads(d.pop("config_json"))
        d["error"] = json.loads(d.pop("error_json")) if d.get("error_json") else None
        return d

    def list(self, limit: int = 50, include_archived: bool = False) -> list[dict]:
        where = "" if include_archived else "WHERE archived_at IS NULL "
        with self.conn() as c:
            rows = c.execute("SELECT id,name,state,stage,progress,message,created_at,updated_at,completed_at,"
                             f"qa_status,attempts FROM jobs {where}ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def transition(self, jid: str, new: str, *, message: str | None = None, error: dict | None = None) -> None:
        if new not in STATES:
            raise StateError(f"unknown state {new}")
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()
            if not r:
                c.execute("ROLLBACK")
                raise NotFound(f"no job {jid!r}")
            old = r["state"]
            if new not in TRANSITIONS[old]:
                c.execute("ROLLBACK")
                raise StateError(f"illegal transition {old} -> {new} for job {jid}")
            now = time.time()
            sets = {"state": new, "updated_at": now, "message": message}
            if new in STAGES:
                sets["stage"] = new
            if new == "PREPARING":
                sets.update(started_at=now, pid=os.getpid(), heartbeat=now, cancel_requested=0, error_json=None)
            if new == "RETRYING":
                c.execute("UPDATE jobs SET attempts=attempts+1 WHERE id=?", (jid,))
            if new in TERMINAL:
                sets.update(completed_at=now if new == "COMPLETED" else None, pid=None)
            if error is not None:
                sets["error_json"] = json.dumps(error)
            c.execute(f"UPDATE jobs SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), jid))
            c.execute("COMMIT")
        self.event(jid, "error" if new == "FAILED" else "info", new, f"{old} -> {new}" + (f": {message}" if message else ""))

    def update(self, jid: str, **fields) -> None:
        allowed = {"progress", "message", "heartbeat", "qa_status", "pid"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"cannot update {bad}")
        fields["updated_at"] = time.time()
        with self.conn() as c:
            c.execute(f"UPDATE jobs SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), jid))

    def heartbeat(self, jid: str) -> None:
        self.update(jid, heartbeat=time.time(), pid=os.getpid())

    def request_cancel(self, jid: str) -> str:
        job = self.get(jid)
        if job["state"] in TERMINAL:
            return job["state"]
        if job["state"] == "QUEUED":
            self.transition(jid, "CANCELLED", message="cancelled before start")
            return "CANCELLED"
        with self.conn() as c:
            c.execute("UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?", (time.time(), jid))
        self.event(jid, "warn", job["state"], "cancellation requested")
        return "CANCEL_REQUESTED"

    def cancel_requested(self, jid: str) -> bool:
        with self.conn() as c:
            r = c.execute("SELECT cancel_requested FROM jobs WHERE id=?", (jid,)).fetchone()
        return bool(r and r[0])

    def recover_stale(self, now: float | None = None) -> list[str]:
        """Active jobs whose worker died (no heartbeat, pid gone) are marked FAILED so they can be retried."""
        now = now or time.time()
        stale = []
        with self.conn() as c:
            rows = c.execute(f"SELECT id, pid, heartbeat, state FROM jobs WHERE state IN ({','.join('?' * len(ACTIVE))})",
                             tuple(ACTIVE)).fetchall()
        for r in rows:
            alive = False
            if r["pid"]:
                try:
                    os.kill(r["pid"], 0)
                    alive = True
                except (ProcessLookupError, PermissionError):
                    alive = False
            if (not alive) or (r["heartbeat"] or 0) < now - STALE_AFTER_S:
                if alive and r["pid"] == os.getpid():
                    continue
                self.transition(r["id"], "FAILED", message="worker died (stale heartbeat)",
                                error={"code": "STALE_JOB", "message": f"worker stopped during {r['state']}",
                                       "transient": True})
                stale.append(r["id"])
        return stale

    # ---- stages (cache records) -----------------------------------------------------------
    def stage_record(self, jid: str, stage: str) -> dict | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM stages WHERE job_id=? AND stage=?", (jid, stage)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["outputs"] = json.loads(d.pop("outputs_json") or "{}")
        return d

    def stage_start(self, jid: str, stage: str, input_hash: str) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO stages (job_id,stage,input_hash,status,started_at) VALUES (?,?,?,?,?)",
                      (jid, stage, input_hash, "RUNNING", time.time()))

    def stage_done(self, jid: str, stage: str, outputs: dict, seconds: float) -> None:
        with self.conn() as c:
            c.execute("UPDATE stages SET status='DONE', finished_at=?, seconds=?, outputs_json=?, error_json=NULL "
                      "WHERE job_id=? AND stage=?", (time.time(), seconds, json.dumps(outputs), jid, stage))

    def stage_failed(self, jid: str, stage: str, error: dict) -> None:
        with self.conn() as c:
            c.execute("UPDATE stages SET status='FAILED', finished_at=?, error_json=? WHERE job_id=? AND stage=?",
                      (time.time(), json.dumps(error), jid, stage))

    def stages(self, jid: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT stage,status,seconds,input_hash,error_json FROM stages WHERE job_id=?", (jid,)).fetchall()
        order = {s: i for i, s in enumerate(STAGES)}
        return sorted((dict(r) for r in rows), key=lambda r: order.get(r["stage"], 99))

    # ---- events ---------------------------------------------------------------------------
    def event(self, jid: str | None, level: str, stage: str | None, message: str, data: dict | None = None) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO events (job_id,ts,level,stage,message,data_json) VALUES (?,?,?,?,?,?)",
                      (jid, time.time(), level, stage, message, json.dumps(data) if data else None))

    def events(self, jid: str, limit: int = 200) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT ts,level,stage,message FROM events WHERE job_id=? ORDER BY id DESC LIMIT ?",
                             (jid, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---- render slots (global concurrency across processes) -------------------------------------
    def acquire_slot(self, jid: str, max_slots: int) -> int | None:
        now = time.time()
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            for r in c.execute("SELECT slot, pid, heartbeat FROM render_slots").fetchall():
                dead = True
                if r["pid"]:
                    try:
                        os.kill(r["pid"], 0)
                        dead = False
                    except (ProcessLookupError, PermissionError):
                        pass
                if dead or (r["heartbeat"] or 0) < now - STALE_AFTER_S:
                    c.execute("DELETE FROM render_slots WHERE slot=?", (r["slot"],))
            used = {r[0] for r in c.execute("SELECT slot FROM render_slots").fetchall()}
            free = [s for s in range(max_slots) if s not in used]
            if not free:
                c.execute("ROLLBACK")
                return None
            c.execute("INSERT INTO render_slots (slot,job_id,pid,acquired_at,heartbeat) VALUES (?,?,?,?,?)",
                      (free[0], jid, os.getpid(), now, now))
            c.execute("COMMIT")
        return free[0]

    def release_slot(self, slot: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM render_slots WHERE slot=?", (slot,))

    def touch_slot(self, slot: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE render_slots SET heartbeat=? WHERE slot=?", (time.time(), slot))
