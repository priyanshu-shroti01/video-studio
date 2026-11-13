"""Production lifecycle and the human approval gate.

A *production* is one creative deliverable (brief -> concept -> storyboard -> render -> approval).
It sits above the v0.2.0 render *job* state machine, which is unchanged:

  DRAFT -> STORYBOARD_READY -> PREVIEW_READY -> RENDERING -> QA_COMPLETE -> AWAITING_APPROVAL
        -> APPROVED -> PUBLISHING -> PUBLISHED
  side states: CHANGES_REQUESTED, REJECTED, FAILED, CANCELLED

Rules enforced here (not just in the UI):
  * Nothing is ever published automatically. QA success only reaches AWAITING_APPROVAL.
  * APPROVED requires an explicit approval record by a named reviewer, made against a package hash,
    with every blocking review flag resolved by a human.
  * The approval is bound to the sha256 of every file in the approval package (videos, thumbnail,
    title, description, hashtags, captions, reports, credits). Any change invalidates it.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .errors import NotFound, PipelineError, StateError
from .jobs import Registry
from .paths import OUTPUT_DIR, ROOT, rel, sha256_file, sha256_json

STATES = ["DRAFT", "STORYBOARD_READY", "PREVIEW_READY", "RENDERING", "QA_COMPLETE", "AWAITING_APPROVAL",
          "APPROVED", "PUBLISHING", "PUBLISHED", "CHANGES_REQUESTED", "REJECTED", "FAILED", "CANCELLED"]
TRANSITIONS = {
    "DRAFT": {"STORYBOARD_READY", "CANCELLED"},
    "STORYBOARD_READY": {"PREVIEW_READY", "RENDERING", "STORYBOARD_READY", "CANCELLED"},
    "PREVIEW_READY": {"RENDERING", "STORYBOARD_READY", "CANCELLED"},
    "RENDERING": {"QA_COMPLETE", "FAILED", "CANCELLED"},
    "QA_COMPLETE": {"AWAITING_APPROVAL", "FAILED"},
    "AWAITING_APPROVAL": {"APPROVED", "REJECTED", "CHANGES_REQUESTED", "AWAITING_APPROVAL"},
    "APPROVED": {"PUBLISHING", "AWAITING_APPROVAL"},          # back to review when invalidated
    "PUBLISHING": {"PUBLISHED", "APPROVED", "FAILED"},
    "PUBLISHED": set(),
    "CHANGES_REQUESTED": {"STORYBOARD_READY", "CANCELLED"},
    "REJECTED": set(),
    "FAILED": {"STORYBOARD_READY", "RENDERING", "CANCELLED"},
    "CANCELLED": set(),
}
BLOCKING, ADVISORY = "blocking", "advisory"
PRODUCTIONS_DIR = OUTPUT_DIR / "productions"


class ApprovalError(PipelineError):
    code, exit_code = "APPROVAL_BLOCKED", 6


class Productions:
    def __init__(self, reg: Registry | None = None):
        self.reg = reg or Registry()

    # ---- records ------------------------------------------------------------------------------
    def create(self, brand: str, name: str, brief: dict | None = None) -> dict:
        pid = "P" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:5]
        d = PRODUCTIONS_DIR / pid
        d.mkdir(parents=True, exist_ok=False)
        now = time.time()
        with self.reg.conn() as c:
            c.execute("INSERT INTO productions (id,brand,name,state,brief_json,dir,created_at,updated_at) "
                      "VALUES (?,?,?,?,?,?,?,?)", (pid, brand, name, "DRAFT", json.dumps(brief or {}), str(d), now, now))
        self.reg.audit("system", "production.create", pid, {"brand": brand, "name": name})
        return self.get(pid)

    def get(self, pid: str) -> dict:
        with self.reg.conn() as c:
            r = c.execute("SELECT * FROM productions WHERE id=?", (pid,)).fetchone()
        if not r:
            raise NotFound(f"no production {pid!r}")
        d = dict(r)
        d["brief"] = json.loads(d.pop("brief_json") or "{}")
        return d

    def list(self, limit: int = 50, include_archived: bool = False) -> list[dict]:
        where = "" if include_archived else "WHERE archived_at IS NULL "
        with self.reg.conn() as c:
            rows = c.execute("SELECT id,brand,name,state,job_id,created_at,updated_at FROM productions "
                             f"{where}ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def update(self, pid: str, **fields) -> None:
        allowed = {"concepts_path", "concept_id", "storyboard_path", "project_path", "job_id", "brief_json"}
        if set(fields) - allowed:
            raise ValueError(f"cannot update {set(fields) - allowed}")
        fields["updated_at"] = time.time()
        with self.reg.conn() as c:
            c.execute(f"UPDATE productions SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), pid))

    def transition(self, pid: str, new: str, actor: str = "system", note: str | None = None) -> None:
        if new not in STATES:
            raise StateError(f"unknown production state {new}")
        with self.reg.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute("SELECT state FROM productions WHERE id=?", (pid,)).fetchone()
            if not r:
                c.execute("ROLLBACK")
                raise NotFound(f"no production {pid!r}")
            if new not in TRANSITIONS[r["state"]]:
                c.execute("ROLLBACK")
                raise StateError(f"illegal production transition {r['state']} -> {new}")
            c.execute("UPDATE productions SET state=?, updated_at=? WHERE id=?", (new, time.time(), pid))
            c.execute("COMMIT")
        self.reg.audit(actor, f"production.{new.lower()}", pid, {"from": r["state"], "note": note})
        _refresh_video_out(self.reg)

    # ---- review flags ---------------------------------------------------------------------------
    def flag(self, pid: str, kind: str, message: str, severity: str = BLOCKING, source: str = "") -> None:
        with self.reg.conn() as c:
            c.execute("INSERT OR IGNORE INTO review_flags (production_id,kind,severity,message,source,created_at) "
                      "VALUES (?,?,?,?,?,?)", (pid, kind, severity, message, source, time.time()))

    def flags(self, pid: str, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM review_flags WHERE production_id=?", [pid]
        if status:
            q += " AND status=?"
            args.append(status)
        with self.reg.conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY severity, id", args).fetchall()]

    def resolve_flag(self, pid: str, flag_id: int, reviewer: str, note: str) -> None:
        if not reviewer.strip() or not note.strip():
            raise ApprovalError("resolving a review flag needs a reviewer name and a note")
        with self.reg.conn() as c:
            n = c.execute("UPDATE review_flags SET status='resolved', resolved_by=?, resolved_at=?, resolution_note=? "
                          "WHERE id=? AND production_id=? AND status='open'",
                          (reviewer, time.time(), note, flag_id, pid)).rowcount
        if not n:
            raise NotFound(f"no open review flag {flag_id} on {pid}")
        self.reg.audit(reviewer, "review_flag.resolve", pid, {"flag": flag_id, "note": note})

    # ---- approval package -----------------------------------------------------------------------
    def package_files(self, pid: str) -> dict[str, Path]:
        """Everything a reviewer approves. Bound into the approval hash."""
        p = self.get(pid)
        if not p["job_id"]:
            raise ApprovalError("production has no completed render job")
        job = self.reg.get(p["job_id"])
        out = Path(job["output_dir"])
        files = {}
        for f in sorted((out / "video").glob("final-*.mp4")):
            files[f"video/{f.name}"] = f
        for name in ("publishing/thumbnail.png", "publishing/title.txt", "publishing/description.md",
                     "publishing/hashtags.txt", "publishing/metadata.json",   # social metadata (pipeline/social)
                     "captions/captions.srt", "reports/qa-report.json",
                     "reports/QA_REPORT.md", "reports/audio-report.json", "assets/manifest.json"):
            if (out / name).exists():
                files[name] = out / name
        for extra in ("reports/branding-report.json", "reports/visual-qa.json", "reports/claims-report.json",
                      "reports/pronunciation-checklist.md", "reports/alignment-report.json"):
            if (out / extra).exists():
                files[extra] = out / extra
        if not any(k.startswith("video/") for k in files):
            raise ApprovalError("no final video in the package")
        return files

    def package_hash(self, pid: str) -> tuple[str, dict[str, str]]:
        hashes = {k: sha256_file(v) for k, v in self.package_files(pid).items()}
        return sha256_json(hashes), hashes

    def build_package(self, pid: str) -> dict:
        """Write approval/APPROVAL_PACKAGE.md + approval-manifest.json and move QA_COMPLETE -> AWAITING_APPROVAL."""
        p = self.get(pid)
        h, hashes = self.package_hash(pid)
        job = self.reg.get(p["job_id"])
        qa = json.loads((Path(job["output_dir"]) / "reports/qa-report.json").read_text())
        manifest = {"production": pid, "brand": p["brand"], "job_id": p["job_id"], "package_hash": h,
                    "files": {k: {"path": rel(v), "sha256": hashes[k]} for k, v in self.package_files(pid).items()},
                    "qa_status": qa["status"], "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "review_flags": self.flags(pid), "published": False}
        adir = Path(p["dir"]) / "approval"
        adir.mkdir(parents=True, exist_ok=True)
        from .paths import atomic_write_json, atomic_write_text
        atomic_write_json(adir / "approval-manifest.json", manifest)
        atomic_write_text(adir / "APPROVAL_PACKAGE.md", self._package_md(p, manifest, qa))
        if p["state"] == "QA_COMPLETE":
            self.transition(pid, "AWAITING_APPROVAL", note=f"package {h[:12]}")
        return manifest

    def _package_md(self, p: dict, m: dict, qa: dict) -> str:
        job_dir = Path(self.reg.get(p["job_id"])["output_dir"])
        title = (job_dir / "publishing/title.txt").read_text().strip() if (job_dir / "publishing/title.txt").exists() else ""
        open_block = [f for f in m["review_flags"] if f["status"] == "open" and f["severity"] == BLOCKING]
        lines = [f"# Approval package — {p['name']} ({p['id']})", "",
                 f"**Brand:** {p['brand']} · **Job:** {p['job_id']} · **QA:** {m['qa_status']} · "
                 f"**Package hash:** `{m['package_hash'][:16]}…`", "",
                 f"**Title:** {title}", "",
                 "> Nothing has been published. Approving records your decision against the exact files below; "
                 "any later change to them invalidates the approval.", "",
                 f"## Review flags ({len(open_block)} blocking open)", ""]
        for f in m["review_flags"]:
            lines.append(f"- [{'x' if f['status'] == 'resolved' else ' '}] **{f['severity']}** `{f['kind']}` — {f['message']}"
                         + (f" _(resolved by {f['resolved_by']}: {f['resolution_note']})_" if f["status"] == "resolved" else ""))
        lines += ["", "## Files (sha256)", "", "| File | sha256 |", "|---|---|"]
        for k, v in m["files"].items():
            lines.append(f"| `{k}` | `{v['sha256'][:16]}…` |")
        counts = {r["format"]: r["counts"] for r in qa.get("formats", [])}
        lines += ["", f"## QA summary", "", "```", json.dumps(counts, indent=1), "```", ""]
        return "\n".join(lines) + "\n"

    # ---- decisions --------------------------------------------------------------------------------
    def approve(self, pid: str, reviewer: str, note: str = "", *, expected_hash: str | None = None) -> dict:
        p = self.get(pid)
        if p["state"] != "AWAITING_APPROVAL":
            raise ApprovalError(f"production is {p['state']}; only AWAITING_APPROVAL can be approved")
        if not reviewer.strip():
            raise ApprovalError("approval needs a named reviewer")
        job = self.reg.get(p["job_id"])
        if job["state"] != "COMPLETED" or job["qa_status"] not in ("PASS", "WARN"):
            raise ApprovalError(f"render job is {job['state']} with QA {job['qa_status']}; approval needs completed QA")
        blocking = [f for f in self.flags(pid, "open") if f["severity"] == BLOCKING]
        if blocking:
            raise ApprovalError(f"{len(blocking)} blocking review flag(s) still open",
                                detail="\n".join(f"#{f['id']} {f['kind']}: {f['message']}" for f in blocking))
        h, _ = self.package_hash(pid)
        built = json.loads((Path(p["dir"]) / "approval/approval-manifest.json").read_text())["package_hash"]
        if h != built:
            raise ApprovalError("package files changed since the approval package was built; rebuild and re-review")
        if expected_hash and expected_hash != h:
            raise ApprovalError("the package you reviewed is not the current package (hash mismatch)")
        with self.reg.conn() as c:
            aid = c.execute("INSERT INTO approvals (production_id,package_hash,decision,reviewer,note,created_at) "
                            "VALUES (?,?,?,?,?,?)", (pid, h, "APPROVED", reviewer, note, time.time())).lastrowid
        self.transition(pid, "APPROVED", actor=reviewer, note=note)
        return {"approval_id": aid, "package_hash": h}

    def decide(self, pid: str, decision: str, reviewer: str, note: str) -> None:
        if decision not in ("REJECTED", "CHANGES_REQUESTED"):
            raise ValueError(decision)
        if not reviewer.strip() or not note.strip():
            raise ApprovalError("a rejection or change request needs a reviewer and a reason")
        h = self.package_hash(pid)[0] if self.get(pid)["job_id"] else ""
        with self.reg.conn() as c:
            c.execute("INSERT INTO approvals (production_id,package_hash,decision,reviewer,note,created_at) "
                      "VALUES (?,?,?,?,?,?)", (pid, h, decision, reviewer, note, time.time()))
        self.transition(pid, decision, actor=reviewer, note=note)

    def current_approval(self, pid: str) -> dict | None:
        """The latest APPROVED record — valid only if the package still hashes the same."""
        with self.reg.conn() as c:
            r = c.execute("SELECT * FROM approvals WHERE production_id=? AND decision='APPROVED' AND invalidated_at IS NULL "
                          "ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        if not r:
            return None
        a = dict(r)
        h, _ = self.package_hash(pid)
        a["valid"] = h == a["package_hash"]
        a["current_hash"] = h
        return a

    def check_approval(self, pid: str) -> dict | None:
        """Re-verify the approval; if any approved file changed, invalidate it and return to review."""
        a = self.current_approval(pid)
        if a and not a["valid"]:
            with self.reg.conn() as c:
                c.execute("UPDATE approvals SET invalidated_at=?, invalidated_reason=? WHERE id=?",
                          (time.time(), "package content changed after approval", a["id"]))
            if self.get(pid)["state"] == "APPROVED":
                self.transition(pid, "AWAITING_APPROVAL", note="approval invalidated: content changed")
            self.reg.audit("system", "approval.invalidated", pid, {"approval": a["id"], "was": a["package_hash"],
                                                                   "now": a["current_hash"]})
            return None
        return a


def flags_from_job(prod: Productions, pid: str, job_out: Path) -> int:
    """Turn job reports into review flags. Blocking: claim/licence/branding problems and the mandatory
    human pronunciation check. Advisory: QA warnings."""
    n = 0
    qa = json.loads((job_out / "reports/qa-report.json").read_text())
    for r in qa.get("formats", []):
        for c in r["checks"]:
            if c["status"] == "WARN":
                prod.flag(pid, f"qa:{c['id']}", f"[{r['format']}] {c['detail']}", ADVISORY, "qa"); n += 1
            elif c["status"] == "FAIL":
                prod.flag(pid, f"qa:{c['id']}", f"[{r['format']}] {c['detail']}", BLOCKING, "qa"); n += 1
    man = json.loads((job_out / "assets/manifest.json").read_text())
    for a in man.get("assets", []):
        lic = a.get("license", "UNKNOWN")
        if lic == "UNKNOWN":
            prod.flag(pid, "license:unknown", f"unknown licence: {a['path']}", BLOCKING, "assets"); n += 1
        elif "test tone" in lic.lower() or "not for publication" in lic.lower():
            prod.flag(pid, "music:test-tone", f"test-only audio must not be published: {a['path']}", BLOCKING, "assets"); n += 1
    claims = job_out / "reports/claims-report.json"
    if claims.exists():
        for c in json.loads(claims.read_text()).get("claims", []):
            if c.get("status") != "VERIFIED":
                prod.flag(pid, "claim:unverified", f"{c.get('text', c)} — {c.get('reason', 'not in approved facts')}",
                          BLOCKING, "claims"); n += 1
    brand = job_out / "reports/branding-report.json"
    if brand.exists():
        for c in json.loads(brand.read_text()).get("checks", []):
            if c.get("status") == "FAIL":
                prod.flag(pid, f"brand:{c['id']}", c["detail"], BLOCKING, "branding"); n += 1
    brand_name = "the brand name"
    try:
        cfgf = job_out / "metadata/production-config.json"
        if cfgf.exists():
            brand_name = f"'{json.loads(cfgf.read_text()).get('brandProfile', {}).get('name') or brand_name}'"
    except (ValueError, OSError):
        pass
    prod.flag(pid, "human:pronunciation", f"Listen to the voiceover: confirm {brand_name}, product names, "
              "domain and technical terms are pronounced acceptably (see reports/pronunciation-checklist.md if present)",
              BLOCKING, "policy"); n += 1
    prod.flag(pid, "human:final-watch", "Watch the final video end to end (picture, captions, sound) before approving",
              BLOCKING, "policy"); n += 1
    return n


def _refresh_video_out(reg) -> None:
    """Keep video-out/ in step with the real registry (never with a test or scratch registry)."""
    from .paths import STATE_DIR
    try:
        if Path(reg.path).resolve() != (STATE_DIR / "registry.db").resolve():
            return
    except OSError:
        return
    from .video_out import sync_quietly
    sync_quietly(reg)
