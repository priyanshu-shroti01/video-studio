"""Job orchestration: PREPARING -> GENERATING_AUDIO -> BUILDING_TIMELINE -> RENDERING ->
POST_PROCESSING -> QA -> COMPLETED.

Each stage has an input hash (config subset + upstream output hashes + code version). If a stage's
recorded input hash matches and every recorded output file still exists with the same sha256, the
stage is skipped — so a render failure never re-runs TTS, and a crash mid-render reuses validated
chunks. Nothing in a COMPLETED job is ever overwritten."""
from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
from pathlib import Path

from . import __version__
from . import audio as A
from . import captions as C
from . import qa as Q
from . import render as R
from . import tts
from .assets import AssetRegistry, check_svg
from .config import theme_asset_paths
from .contract import CONTRACT_VERSION, FORMATS, ts_contract_version
from .errors import Cancelled, PipelineError, QAFailed, StateError
from .jobs import STAGES, Registry
from .paths import (ROOT, atomic_write_json, atomic_write_text, publish_file, rel, safe_path, sha256_file,
                    sha256_json)
from .storyboard import Resolver, SceneTiming, auto_sfx, resolve_block
from .timing import Word, align, validate_words


class JobRunner:
    def __init__(self, reg: Registry, jid: str, *, echo=print):
        self.reg, self.jid, self.echo = reg, jid, echo
        job = reg.get(jid)
        self.cfg = job["config"]
        self.out = Path(job["output_dir"])
        self.d = {k: self.out / k for k in ("video", "audio", "captions", "assets", "previews", "reports", "metadata",
                                            "publishing", "logs", "work")}
        self._stop_hb = threading.Event()

    # ---- logging -----------------------------------------------------------------------------
    def log(self, msg: str, level: str = "info", stage: str | None = None, **data):
        self.echo(f"[{self.jid}] {msg}")
        rec = {"ts": round(time.time(), 3), "job": self.jid, "level": level, "stage": stage, "msg": msg, **data}
        self.d["logs"].mkdir(parents=True, exist_ok=True)
        with open(self.d["logs"] / "pipeline.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if level in ("warn", "error") or stage:
            self.reg.event(self.jid, level, stage, msg, data or None)

    def cancelled(self) -> bool:
        return self.reg.cancel_requested(self.jid)

    def _heartbeat(self):
        while not self._stop_hb.wait(5):
            try:
                self.reg.heartbeat(self.jid)
            except Exception:  # noqa: BLE001 - heartbeat must never crash the job
                pass

    # ---- driver --------------------------------------------------------------------------------
    def run(self) -> dict:
        job = self.reg.get(self.jid)
        if job["state"] == "COMPLETED":
            raise StateError(f"job {self.jid} is already COMPLETED; outputs are never overwritten "
                             "(create a new job with --force to produce another copy)")
        if job["state"] in ("FAILED", "CANCELLED"):
            self.reg.transition(self.jid, "RETRYING", message="resuming from cached stages")
        for k in self.d.values():
            k.mkdir(parents=True, exist_ok=True)
        self.reg.transition(self.jid, "PREPARING")
        hb = threading.Thread(target=self._heartbeat, daemon=True)
        hb.start()
        stage = "PREPARING"
        try:
            ctx: dict = {}
            for i, stage in enumerate(STAGES):
                if i:
                    self.reg.transition(self.jid, stage)
                if self.cancelled():
                    raise Cancelled("cancelled by user")
                getattr(self, "stage_" + stage.lower())(ctx)
            self.reg.transition(self.jid, "COMPLETED", message=f"outputs in {rel(self.out)}")
            self.log("COMPLETED", stage="COMPLETED")
            return self.reg.get(self.jid)
        except KeyboardInterrupt:  # Ctrl-C / SIGTERM (cli converts it): children are already killed by procs
            err = {"code": "INTERRUPTED", "message": f"interrupted during {stage}", "transient": True}
            self.log(err["message"], "warn", stage)
            self.reg.stage_failed(self.jid, stage, err)
            self.reg.transition(self.jid, "CANCELLED", message=err["message"], error=err)
            raise
        except Cancelled as e:
            self.log(f"cancelled during {stage}", "warn", stage)
            self.reg.stage_failed(self.jid, stage, e.to_dict())
            self.reg.transition(self.jid, "CANCELLED", message=f"cancelled during {stage}", error=e.to_dict())
            raise
        except PipelineError as e:
            self.log(f"{stage} failed: {e.message}", "error", stage, detail=(e.detail or "")[-2000:])
            self.reg.stage_failed(self.jid, stage, e.to_dict())
            self.reg.transition(self.jid, "FAILED", message=f"{stage}: {e.message}", error={**e.to_dict(), "stage": stage})
            raise
        except Exception as e:  # unexpected bug: record it fully, never swallow
            err = {"code": "INTERNAL", "message": f"{type(e).__name__}: {e}", "transient": False, "stage": stage,
                   "detail": traceback.format_exc()[-3000:]}
            self.log(f"{stage} crashed: {err['message']}", "error", stage)
            self.reg.stage_failed(self.jid, stage, err)
            self.reg.transition(self.jid, "FAILED", message=f"{stage}: internal error", error=err)
            raise
        finally:
            self._stop_hb.set()

    def cached(self, stage: str, input_hash: str) -> dict | None:
        rec = self.reg.stage_record(self.jid, stage)
        if not rec or rec["status"] != "DONE" or rec["input_hash"] != input_hash:
            return None
        for f in rec["outputs"].get("files", {}).values():
            p = ROOT / f["path"]
            if not p.exists() or sha256_file(p) != f["sha256"]:
                self.log(f"{stage}: cached output {f['path']} missing or changed; re-running", "warn", stage)
                return None
        self.log(f"{stage}: reusing validated outputs (cache hit)", stage=stage)
        return rec["outputs"]

    def done(self, stage: str, ih: str, t0: float, files: dict[str, Path], data: dict | None = None) -> dict:
        outputs = {"files": {k: {"path": rel(p), "sha256": sha256_file(p)} for k, p in files.items()}, "data": data or {}}
        self.reg.stage_done(self.jid, stage, outputs, round(time.time() - t0, 2))
        self.log(f"{stage}: done in {time.time() - t0:.1f}s", stage=stage)
        return outputs

    def begin(self, stage: str, ih: str) -> float:
        self.reg.stage_start(self.jid, stage, ih)
        return time.time()

    # ---- stages --------------------------------------------------------------------------------
    def stage_preparing(self, ctx):
        cfg = self.cfg
        ih = sha256_json({"v": __version__, "cfg": cfg})
        if (o := self.cached("PREPARING", ih)):
            ctx["prep"] = o["data"]
            return
        t0 = self.begin("PREPARING", ih)
        if ts_contract_version() != CONTRACT_VERSION:
            raise PipelineError(f"render contract mismatch: python v{CONTRACT_VERSION}, engine v{ts_contract_version()}")
        res = R.preflight(cfg.get("render", {}).get("minFreeGb", 2.0))
        ar = AssetRegistry(self.reg)
        used = []
        for a in theme_asset_paths(cfg["theme"]):
            p = safe_path(Path("public") / a, must_exist=True)
            if p.suffix == ".svg":
                check_svg(p)
            used.append(ar.register(p, ref=self.jid))
        if cfg.get("audio", {}).get("music"):
            used.append(ar.register(safe_path(cfg["audio"]["music"], must_exist=True), ref=self.jid))
        # footage clips go into the asset manifest with their licence record (unknown licence -> blocking review flag)
        from .footage import footage_blocks, public_file
        for clip in sorted({b["asset"] for _, b in footage_blocks(cfg["storyboard"])}):
            used.append(ar.register(public_file(clip), ref=self.jid))
        atomic_write_json(self.d["metadata"] / "production-config.json", cfg)
        atomic_write_json(self.d["metadata"] / "storyboard.source.json", cfg["storyboard"])
        atomic_write_json(self.d["metadata"] / "job-manifest.json", {
            "job_id": self.jid, "name": cfg["name"], "pipeline_version": __version__, "contract": CONTRACT_VERSION,
            "formats": cfg["formats"], "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "preflight": res})
        ctx["prep"] = {"assets": used, "preflight": res}
        self.done("PREPARING", ih, t0, {"config": self.d["metadata"] / "production-config.json"}, ctx["prep"])

    def stage_generating_audio(self, ctx):
        v = self.cfg["voice"]
        scenes = self.cfg["storyboard"]["scenes"]
        ih = sha256_json({"voice": v, "vfp": tts.voice_fingerprint(v), "narr": [s["narration"] for s in scenes],
                          "hold": [s.get("holdAfter", 0) for s in scenes], "v": __version__})
        if (o := self.cached("GENERATING_AUDIO", ih)):
            ctx["timing"] = json.loads((ROOT / o["files"]["timing"]["path"]).read_text())
            return
        t0 = self.begin("GENERATING_AUDIO", ih)
        per = []
        from .scheduler import HeavyWork
        heavy = HeavyWork(self.reg, "tts", ref=self.jid, should_cancel=self.cancelled, log=self.log) \
            if v["provider"] not in ("mock", "edge") else None   # local TTS models are memory-heavy
        if heavy:
            g = heavy.__enter__()
            self.log(f"scheduler: tts granted after {g.waited_s}s ({g.available_mb} MB available)")
        try:
            per = self._synthesize_scenes(scenes, v)
        finally:
            tts.unload_all()                      # free the TTS worker before rendering needs the memory
            if heavy:
                heavy.__exit__(None, None, None)
        vo = A.build_voiceover(per, self.d["audio"] / "voiceover.wav", max_pause=v.get("maxPause", 0.35),
                               pad=v.get("pad", 0.25), gap=v.get("sceneGap", 0.2))
        self._finish_audio(vo, v, ih, t0, ctx)

    def _synthesize_scenes(self, scenes, v):
        per = []
        self._align_log = []
        for k, sc in enumerate(scenes):
            if self.cancelled():
                raise Cancelled("cancelled during voice generation")
            res = tts.synthesize_from_config(sc["narration"], v,
                                             on_retry=lambda n, e, d: self.log(f"TTS retry {n} in {d:.1f}s: {e}",
                                                                               "warn", "GENERATING_AUDIO"))
            words = align(sc["narration"], res.boundaries, res.duration)
            rep = validate_words(words, res.duration, script=sc["narration"])
            if not rep.ok:
                raise PipelineError(f"scene {sc['id']}: invalid word timings", detail="\n".join(rep.errors))
            for w in rep.warnings:
                self.log(f"scene {sc['id']}: {w}", "warn", "GENERATING_AUDIO")
            eng = res.meta.get("engine") or {}
            self.log(f"voice {k + 1}/{len(scenes)} '{sc['id']}': {res.duration:.2f}s, {len(words)} words "
                     f"({res.meta.get('provider', v['provider'])}/{v['voice']}, timing {eng.get('timing_method', 'n/a')}, "
                     f"cache {res.meta.get('cache')})")
            self._align_log.append({"scene": sc["id"], "duration": round(res.duration, 3), "words": len(words),
                                    "timing_method": eng.get("timing_method"), "warnings": rep.warnings,
                                    "interpolated": rep.interpolated, "fixed_overlaps": rep.fixed_overlaps})
            per.append(A.SceneVoice(res.audio, words, res.duration, hold=float(sc.get("holdAfter", 0.0))))
            self.reg.update(self.jid, progress=round((k + 1) / len(scenes), 3))
        return per

    def _finish_audio(self, vo, v, ih, t0, ctx):
        rep = validate_words(vo.words, vo.duration, fix=False)
        if not rep.ok:
            raise PipelineError("assembled voiceover timings are invalid", detail="\n".join(rep.errors))
        timing = {"duration": vo.duration, "words": [w.as_dict() for w in vo.words], "scene_spans": vo.scene_spans,
                  "removed_pause_s": vo.removed_s, "report": rep.as_dict(), "voice": v}
        atomic_write_json(self.d["metadata"] / "timing.json", timing)
        atomic_write_json(self.d["reports"] / "alignment-report.json",
                          {"provider": v["provider"], "voice": v["voice"], "scenes": getattr(self, "_align_log", []),
                           "assembled": rep.as_dict(), "duration": vo.duration})
        ctx["timing"] = timing
        self.log(f"voiceover {vo.duration:.2f}s ({len(vo.words)} words, {vo.removed_s:.2f}s of pauses removed)")
        self.done("GENERATING_AUDIO", ih, t0, {"voiceover": vo.path, "timing": self.d["metadata"] / "timing.json"})

    def stage_building_timeline(self, ctx):
        cfg, tm = self.cfg, ctx["timing"]
        ih = sha256_json({"t": sha256_json(tm), "sb": cfg["storyboard"], "cap": cfg["captions"], "theme": cfg["theme"],
                          "fmt": cfg["formats"], "audio": cfg["audio"], "brand": cfg.get("brandProfile"),
                          "branding": cfg.get("branding"), "motion": cfg.get("motion"), "contract": CONTRACT_VERSION,
                          "v": __version__})
        if (o := self.cached("BUILDING_TIMELINE", ih)):
            ctx["tl"] = o["data"]
            return
        t0 = self.begin("BUILDING_TIMELINE", ih)
        from .timeline import build_timeline
        tl = build_timeline(cfg, tm)
        for w in tl.warnings:
            self.log(w, "warn", "BUILDING_TIMELINE")
        files = {}
        srt = self.d["captions"] / "captions.srt"
        atomic_write_text(srt, tl.srt)
        files["srt"] = srt
        props_hashes = {}
        for fmt, props in tl.props.items():
            ass = self.d["captions"] / f"captions-{fmt}.ass"
            atomic_write_text(ass, tl.ass[fmt])
            files[f"ass_{fmt}"] = ass
            pf = self.d["metadata"] / f"props-{fmt}.json"
            atomic_write_json(pf, props)
            files[f"props_{fmt}"] = pf
            props_hashes[fmt] = sha256_file(pf)
        atomic_write_json(self.d["metadata"] / "storyboard.json", tl.storyboard_out)
        atomic_write_json(self.d["metadata"] / "sfx-cues.json", tl.sfx)
        files["storyboard"] = self.d["metadata"] / "storyboard.json"
        files["sfx"] = self.d["metadata"] / "sfx-cues.json"
        ctx["tl"] = {"duration": tl.duration, "frames": tl.frames, "fps": tl.fps,
                     "scene_starts": [s["start"] for s in tl.resolved], "props_hashes": props_hashes,
                     "n_sfx": len(tl.sfx), "max_cps": tl.max_cps,
                     "branding": bool(tl.brand_bar) or any(b["type"] in ("logo", "cta", "logo-sting")
                                                            for s in tl.resolved for b in s["blocks"])}
        self.log(f"timeline: {len(tl.resolved)} scenes, {tl.frames} frames ({tl.duration:.2f}s), {len(tl.pages)} caption "
                 f"pages, {len(tl.sfx)} sfx cues")
        self.done("BUILDING_TIMELINE", ih, t0, files, ctx["tl"])

    def stage_rendering(self, ctx):
        cfg, tl = self.cfg, ctx["tl"]
        bundle = R.ensure_bundle(lambda m: self.log(m))
        ih = sha256_json({"props": tl["props_hashes"], "render": cfg.get("render", {}), "bundle": bundle.name})
        if (o := self.cached("RENDERING", ih)):
            ctx["videos"] = o["data"]["videos"]
            return
        t0 = self.begin("RENDERING", ih)
        R.ensure_chromium()
        max_jobs = int(cfg.get("render", {}).get("maxJobs", 1))
        slot = R.acquire_render_slot(self.reg, self.jid, max_jobs, self.cancelled, self.log)
        reports, files, videos = [], {}, {}
        from .scheduler import HeavyWork
        heavy = HeavyWork(self.reg, "render", ref=self.jid, should_cancel=self.cancelled, log=self.log)
        try:
            g = heavy.__enter__()
            self.log(f"scheduler: render granted after {g.waited_s}s ({g.available_mb} MB available)")
            fmts = cfg["formats"]
            for fi, fmt in enumerate(fmts):
                s = R.RenderSettings.from_config(cfg.get("render", {}), fmt)
                out = self.d["work"] / f"video-{fmt}.mp4"

                def prog(p, fi=fi):
                    self.reg.update(self.jid, progress=round((fi + p) / len(fmts), 3))
                    self.reg.touch_slot(slot)
                rep = R.render_format(props_file=self.d["metadata"] / f"props-{fmt}.json",
                                      props_hash=tl["props_hashes"][fmt], fmt=fmt, total_frames=tl["frames"],
                                      fps=tl["fps"], out=out, chunks_dir=self.d["work"] / "chunks", s=s, bundle=bundle,
                                      should_cancel=self.cancelled, log=lambda m: self.log(m), on_progress=prog)
                reports.append(rep.as_dict())
                files[f"video_{fmt}"] = out
                videos[fmt] = rel(out)
                self.log(f"[{fmt}] rendered {rep.frames} frames in {rep.seconds:.1f}s "
                         f"({rep.as_dict()['realtime_factor']}x realtime, encoder {rep.encoder})")
        finally:
            heavy.__exit__(None, None, None)
            self.reg.release_slot(slot)
        atomic_write_json(self.d["reports"] / "render-report.json", {"bundle": bundle.name, "formats": reports})
        ctx["videos"] = videos
        self.done("RENDERING", ih, t0, files, {"videos": videos})

    def stage_post_processing(self, ctx):
        cfg, tl, tm = self.cfg, ctx["tl"], ctx["timing"]
        a = cfg["audio"]
        music = a.get("music")
        vids = {f: ROOT / p for f, p in ctx["videos"].items()}
        sfx = json.loads((self.d["metadata"] / "sfx-cues.json").read_text())
        ih = sha256_json({"v": {f: sha256_file(p) for f, p in vids.items()}, "vo": sha256_file(self.d["audio"] / "voiceover.wav"),
                          "sfx": sfx, "audio": a, "music": sha256_file(ROOT / music) if music else None,
                          "pub": cfg.get("publishing", {}), "ver": __version__})
        if (o := self.cached("POST_PROCESSING", ih)):
            ctx["finals"] = o["data"]["finals"]
            ctx["mix"] = o["data"]["mix"]
            return
        t0 = self.begin("POST_PROCESSING", ih)
        kit = A.Kit(ROOT / a.get("kit", "audio/kit"))
        events = [A.SfxEvent(e["sound"], e["t"], e["gain"], e.get("kind", "")) for e in sfx]
        settings = A.MixSettings.from_config(a)
        mixed = self.d["audio"] / "mixed-audio.wav"
        mres = A.mix(out=mixed, duration=tl["duration"], voice=[(self.d["audio"] / "voiceover.wav", 0.0)],
                     music=ROOT / music if music else None, sfx=events, kit=kit, s=settings,
                     stems_dir=self.d["work"] / "stems")
        words = [Word(w["text"], w["start"], w["end"]) for w in tm["words"]]
        analysis = A.analyze(mixed)
        duck = A.ducking_depth(mres.stems, words)
        audio_rep = {"mix": analysis, "ducking": duck, "settings": settings.__dict__, "sfx_events": mres.events,
                     "voiceover": A.analyze(self.d["audio"] / "voiceover.wav")}
        atomic_write_json(self.d["reports"] / "audio-report.json", audio_rep)
        self.log(f"mix: {analysis['integrated_lufs']} LUFS, TP {analysis['true_peak_dbtp']} dBTP, "
                 f"{analysis['clipped_samples']} clipped, ducking {duck and duck['under_voice_db']} dB")
        finals, files = {}, {"mix": mixed}
        for fmt, v in vids.items():
            dst = self.d["video"] / f"final-{fmt}.mp4"
            tmp = self.d["video"] / f".final-{fmt}.part.mp4"
            tmp.unlink(missing_ok=True)
            from . import procs
            procs.run(["ffmpeg", "-v", "error", "-y", "-i", str(v), "-i", str(mixed), "-map", "0:v:0", "-map", "1:a:0",
                       "-c:v", "copy", "-bsf:v",
                       "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0",
                       "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(tmp)],
                      timeout=600)
            if dst.exists():
                dst.unlink()  # same job, not COMPLETED yet (run() refuses completed jobs)
            publish_file(tmp, dst)
            finals[fmt] = rel(dst)
            files[f"final_{fmt}"] = dst
        # previews + publishing package
        first = next(iter(vids))
        prev = self.d["previews"] / "preview.mp4"
        procs.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / finals[first]), "-vf", "scale=-2:640", "-c:v", "libx264",
                   "-crf", "30", "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k", str(prev)], timeout=600)
        pub = cfg.get("publishing", {})
        title = pub.get("title", cfg["name"])
        thumb_t = pub.get("thumbnailAt", tl["scene_starts"][-1] + 1.2)
        procs.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{min(thumb_t, tl['duration'] - 0.2):.2f}", "-i",
                   str(ROOT / finals[first]), "-frames:v", "1", str(self.d["publishing"] / "thumbnail.png")], timeout=60)
        atomic_write_text(self.d["publishing"] / "title.txt", title.strip() + "\n")
        atomic_write_text(self.d["publishing"] / "hashtags.txt", " ".join(pub.get("hashtags", [])) + "\n")
        credits = sorted({(e["sound"], e["file"]) for e in mres.events})
        from .assets import AssetRegistry, license_for
        ar = AssetRegistry(self.reg)
        sfx_assets = [ar.register(Path(f), ref=self.jid) for _, f in credits]
        desc = [pub.get("description", "").strip(), "", "---", "Transcript:", " ".join(w["text"] for w in tm["words"]), ""]
        lic = [f"- {x['attribution'] or Path(x['path']).name} — {x['license']} ({x['source']})" for x in sfx_assets]
        if lic:
            desc += ["Sound effects:", *lic, ""]
        atomic_write_text(self.d["publishing"] / "description.md", "\n".join(desc))
        manifest = {"job_id": self.jid, "assets": ctx.get("prep", {}).get("assets", []) + sfx_assets,
                    "unknown_licenses": [x["path"] for x in ctx.get("prep", {}).get("assets", []) + sfx_assets
                                         if x["license"] == "UNKNOWN"]}
        atomic_write_json(self.d["assets"] / "manifest.json", manifest)
        if manifest["unknown_licenses"]:
            self.log(f"assets with unknown licence: {manifest['unknown_licenses']}", "warn", "POST_PROCESSING")
        ctx["finals"], ctx["mix"] = finals, {"events": len(mres.events), "stems": mres.stems}
        self.done("POST_PROCESSING", ih, t0, files, {"finals": finals, "mix": ctx["mix"]})

    def _sync_checks(self, fmt: str, final: str, words: list[dict], tl: dict) -> list:
        """A/V offset (measured) + narration-to-visual sync (from the props actually rendered)."""
        from . import sync_check as S
        out = []
        try:
            av = S.av_offset(self.d["audio"] / "voiceover.wav", ROOT / final)
            lag = av["max_abs_lag_ms"]
            ok = lag is not None and lag <= 45 and abs(av["drift_ms"] or 0) <= 45
            out.append(Q.Check("sync.av_offset", "sync", Q.PASS if ok else Q.FAIL, True,
                               f"voice in video vs voiceover: max lag {lag} ms, drift {av['drift_ms']} ms over "
                               f"{av['windows']} windows (limit 45 ms ≈ 1.4 frames)", {k: v for k, v in av.items() if k != "lags"}))
        except Exception as e:  # noqa: BLE001 - recorded, never silently skipped
            out.append(Q.Check("sync.av_offset", "sync", Q.FAIL, True, f"A/V offset could not be measured: {e}"))
        props = json.loads((self.d["metadata"] / f"props-{fmt}.json").read_text())
        r = S.evaluate(props["scenes"], words, props["durationInFrames"] / props["fps"])
        # not critical for the job (the preview gate blocks this before rendering), but visible in QA and review
        out.append(Q.Check("sync.narration_visual", "sync", r["status"], False, S.summary(r),
                           {k: r[k] for k in ("longest_static_s", "static_share_pct", "events")}))
        return out

    def stage_qa(self, ctx):
        cfg, tl, tm = self.cfg, ctx["tl"], ctx["timing"]
        t0 = self.begin("QA", sha256_json({"finals": ctx["finals"], "t": time.time()}))
        q = cfg.get("qa", {})
        words = tm["words"]
        reports = []
        visual_by_fmt: dict = {}
        for fmt, p in ctx["finals"].items():
            capf = {**cfg["captions"], **cfg.get("captionsByFormat", {}).get(fmt, {})}
            ex = Q.Expect(fmt=fmt, fps=tl["fps"], duration=tl["frames"] / tl["fps"], require_audio=True,
                          lufs=cfg["audio"].get("lufs", -14), lufs_tol=q.get("lufsTolerance", 1.0),
                          max_true_peak=q.get("maxTruePeak", -1.0),
                          speech=[(w["start"], w["end"]) for w in words], scene_starts=tl["scene_starts"],
                          freeze_warn_s=q.get("freezeWarnS", 3.0), planned_sfx=tl["n_sfx"], placed_sfx=ctx["mix"]["events"]
                          if isinstance(ctx["mix"]["events"], int) else len(ctx["mix"]["events"]),
                          caption_bottom_frac=capf.get("bottomFrac") if fmt == "short" else None,
                          min_caption_bottom_frac=q.get("shortsOverlayFrac", 0.2), branding_present=tl["branding"])
            extra = []
            if q.get("visual", True):
                from .visual_qa.checks import run_visual_qa
                try:
                    extra = run_visual_qa(self.out, fmt,
                                          self.d["metadata"] / f"props-{fmt}.json", ROOT / p, cfg["theme"])
                except Exception as e:  # noqa: BLE001 - recorded as a failed check, never silently skipped
                    extra = [Q.Check("visual_qa.run", "visual", Q.FAIL, True, f"visual QA could not run: {e}")]
                visual_by_fmt[fmt] = extra
            extra = [*extra, *self._sync_checks(fmt, p, words, tl)]
            rep = Q.run_qa(ROOT / p, ex, srt=self.d["captions"] / "captions.srt",
                           ass=self.d["captions"] / f"captions-{fmt}.ass", words=words, reports_dir=self.d["reports"],
                           previews_dir=self.d["previews"] / fmt, max_cps=cfg["captions"].get("maxCps", 25),
                           title=cfg["name"], extra=extra)
            reports.append(rep)
            self.log(f"QA [{fmt}]: {rep['status']} ({rep['counts']})", "info" if rep["status"] != "FAIL" else "error", "QA")
        Q.write_markdown(reports, self.d["reports"] / "QA_REPORT.md", cfg["name"])
        if visual_by_fmt:
            from .visual_qa.checks import write_branding_report
            write_branding_report(self.out, visual_by_fmt)
        try:
            from .visual_qa.review import pronunciation_checklist
            md, items = pronunciation_checklist(cfg, tm)
            atomic_write_text(self.d["reports"] / "pronunciation-checklist.md", md)
        except Exception as e:  # noqa: BLE001
            self.log(f"pronunciation checklist unavailable: {e}", "warn", "QA")
        overall = "FAIL" if any(r["status"] == "FAIL" for r in reports) else (
            "WARN" if any(r["status"] == "WARN" for r in reports) else "PASS")
        atomic_write_json(self.d["reports"] / "qa-report.json", {"status": overall, "formats": reports})
        self.reg.update(self.jid, qa_status=overall)
        if overall == "FAIL":
            fails = [f"{r['format']}:{c['id']}" for r in reports for c in r["checks"] if c["status"] == "FAIL" and c["critical"]]
            raise QAFailed(f"critical QA checks failed: {fails}", detail=json.dumps(fails))
        self.done("QA", "", t0, {"qa": self.d["reports"] / "qa-report.json"}, {"status": overall})


def run_qa_only(reg: Registry, jid: str, echo=print) -> dict:
    """Re-run QA for any job with finished videos (also COMPLETED ones): only reports are rewritten."""
    r = JobRunner(reg, jid, echo=echo)
    ctx = {}
    for st, key in (("GENERATING_AUDIO", "timing"), ("BUILDING_TIMELINE", "tl"), ("POST_PROCESSING", "finals")):
        rec = reg.stage_record(jid, st)
        if not rec or rec["status"] != "DONE":
            raise PipelineError(f"job has not finished {st}; nothing to QA yet")
        if key == "timing":
            ctx["timing"] = json.loads((ROOT / rec["outputs"]["files"]["timing"]["path"]).read_text())
        elif key == "tl":
            ctx["tl"] = rec["outputs"]["data"]
        else:
            ctx["finals"], ctx["mix"] = rec["outputs"]["data"]["finals"], rec["outputs"]["data"]["mix"]
    r.stage_qa(ctx)
    return json.loads((r.d["reports"] / "qa-report.json").read_text())


def clean(reg: Registry, *, dry_run: bool = True) -> list[tuple[str, int]]:
    """Removes only regenerable intermediates: work/ of COMPLETED jobs, tmp files, stale bundles.
    Never touches final videos, reports, or the TTS cache of active jobs."""
    from .paths import OUTPUT_DIR, TMP_DIR
    targets = []
    for job in reg.list(limit=10_000):
        if job["state"] == "COMPLETED":
            w = OUTPUT_DIR / job["id"] / "work"
            if w.exists():
                targets.append(w)
    if TMP_DIR.exists():
        targets += [p for p in TMP_DIR.iterdir()]
    for p in (ROOT / ".pipeline" / "bundles").glob(".tmp-*"):
        targets.append(p)
    out = []
    for t in targets:
        size = sum(f.stat().st_size for f in t.rglob("*") if f.is_file()) if t.is_dir() else t.stat().st_size
        out.append((rel(t), size))
        if not dry_run:
            safe_path(t)  # inside the workspace, or refuse
            shutil.rmtree(t) if t.is_dir() else t.unlink()
    return out
