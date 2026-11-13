"""Voice evaluation: synthesize the real Shroti Host narration with every installed candidate voice and
measure what a machine can measure (speed, memory, ASR intelligibility, brand-term recognition,
speaking rate, pauses, timing accuracy). Naturalness and accent still need a human: see the generated
output/eval-voice/LISTENING_CHECKLIST.md.

    uv run python -m pipeline.voice.evaluate run          # everything (one subprocess per engine/voice)
    uv run python -m pipeline.voice.evaluate report       # rebuild tables from saved JSON
"""
from __future__ import annotations

import difflib
import json
import os
import re
import resource
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

from ..paths import ROOT

OUT = ROOT / "output" / "eval-voice"
STORYBOARD = ROOT / "projects" / "shrotihost-short.storyboard.json"
RATE = "+5%"   # shorts preset
BRAND = ("shroti", "shrohtee", "shrotee", "shrotihost")
BRAND_ID = "shrotihost"          # the brand whose real narration this evaluation uses


def _pron() -> dict:
    from ..brands import load_pronunciation
    return load_pronunciation(BRAND_ID)
HOMOPHONES = {"light": "lite"}   # "Lite Speed" heard as "light speed" is not an intelligibility error


def candidates() -> list[tuple[str, str, str | None]]:
    from . import registry
    c = [("kokoro", v, None) for v in registry.voices("kokoro")]
    c.append(("kokoro", "hm_omega", "en-gb"))   # Hindi male voice with British (non-rhotic) phonemes
    c.append(("kokoro", "hf_alpha", "en-gb"))
    c += [("piper", v, None) for v in registry.voices("piper")]
    return c


def tag(p, v, lang):
    return f"{p}-{v}" + (f"-{lang}" if lang else "")


def scenes() -> list[dict]:
    return json.loads(STORYBOARD.read_text())["scenes"]


def swap_used_mb() -> float:
    out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    m = re.search(r"used = ([\d.]+)M", out)
    return float(m.group(1)) if m else float("nan")


def contention() -> dict:
    def n(pat):
        r = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True)
        return len(r.stdout.split())
    return {"chrome_headless_shell": n("chrome-headless-shell"), "ollama": n("ollama"),
            "ollama_runner": n("ollama runner")}


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # bytes on macOS


# ---------------------------------------------------------------------------------------------
def synth(provider: str, voice: str, lang: str | None) -> dict:
    """Runs in its own process so peak RSS is this engine+voice alone."""
    from .. import audio as A
    from .. import tts
    from ..timing import align, validate_words
    t = tag(provider, voice, lang)
    d = OUT / t
    d.mkdir(parents=True, exist_ok=True)
    swap0, cont = swap_used_mb(), contention()
    rss0 = rss_mb()
    prov = tts.get_provider(provider)
    t0 = time.perf_counter()
    if provider == "kokoro":
        prov.load()
    else:
        prov.load(voice)
    load_s = time.perf_counter() - t0
    rss_load = rss_mb()
    rows, per, synth_total, audio_total = [], [], 0.0, 0.0
    opts = {"lang": lang} if lang else None
    for k, sc in enumerate(scenes()):
        cache = d / "cache"
        t1 = time.perf_counter()
        r = tts.synthesize(sc["narration"], provider=provider, voice=voice, rate=RATE, cache_dir=cache, options=opts)
        wall = time.perf_counter() - t1
        eng = r.meta.get("engine", {})
        synth_total += eng.get("synth_s", wall)
        audio_total += r.duration
        words = align(sc["narration"], r.boundaries, r.duration)
        rep = validate_words(words, r.duration, script=sc["narration"])
        wav = d / f"scene-{k + 1:02d}-{sc['id']}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(r.audio), "-c:a", "pcm_s16le", str(wav)], check=True)
        rows.append({"scene": sc["id"], "text": sc["narration"], "spoken": r.meta["spoken"], "wav": wav.name,
                     "duration": r.duration, "synth_s": eng.get("synth_s"), "wall_s": round(wall, 3),
                     "timing_method": eng.get("timing_method"), "align": r.meta.get("align"),
                     "validation": rep.as_dict(), "words": [w.as_dict() for w in words],
                     "spoken_boundaries": r.meta["spoken_boundaries"]})
        per.append(A.SceneVoice(wav, words, r.duration))
    vo = A.build_voiceover(per, d / "narration.wav", max_pause=0.35, pad=0.25, gap=0.2)
    res = {"tag": t, "provider": provider, "voice": voice, "lang": lang or getattr(prov, "lang_for", lambda v, o: None)(voice, None),
           "load_s": round(load_s, 3), "synth_s": round(synth_total, 3), "audio_s": round(audio_total, 3),
           "rtf": round(synth_total / audio_total, 4), "rss_before_mb": round(rss0), "rss_after_load_mb": round(rss_load),
           "peak_rss_mb": round(rss_mb()), "swap_delta_mb": round(swap_used_mb() - swap0, 1), "contention": cont,
           "narration_s": round(vo.duration, 3), "narration_wav": str((d / "narration.wav").relative_to(OUT)),
           "scenes": rows}
    prov.unload()
    (d / "synth.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


# ---------------------------------------------------------------------------------------------
def _norm_words(text: str) -> list[str]:
    from . import pronunciation as P
    try:
        sp = P.prepare(text, _pron()).spoken
    except ValueError:
        sp = text
    sp = sp.lower().replace("’", "'")
    words = [w for w in (re.sub(r"[^a-z0-9]", "", x) for x in sp.split()) if w]   # "shro-tee" -> "shrotee"
    return [HOMOPHONES.get(w, w) for w in words]


def wer(ref: list[str], hyp: list[str]) -> tuple[float, list[tuple[str, str]]]:
    n, m = len(ref), len(hyp)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        D[i][0] = i
    for j in range(m + 1):
        D[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]), D[i - 1][j] + 1, D[i][j - 1] + 1)
    i, j, subs = n, m, []
    while i and j:
        if D[i][j] == D[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                subs.append((ref[i - 1], hyp[j - 1]))
            i -= 1; j -= 1
        elif D[i][j] == D[i - 1][j] + 1:
            subs.append((ref[i - 1], "")); i -= 1
        else:
            subs.append(("", hyp[j - 1])); j -= 1
    subs += [(ref[k], "") for k in range(i)] + [("", hyp[k]) for k in range(j)]
    return D[n][m] / max(1, n), subs[::-1]


def _brand_heard(hyp_text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z][A-Za-z.'-]*", hyp_text)
    out = []
    for k, t in enumerate(toks):
        low = re.sub(r"^www\.", "", t.lower().strip("."))
        if any(difflib.SequenceMatcher(None, low[:len(b) + 2], b).ratio() >= 0.7 for b in BRAND):
            out.append(" ".join(toks[k:k + 3]))
    return out


def asr_eval() -> dict:
    from ..timing import align
    from ..tts import Boundary
    from .asr import Whisper
    swap0, cont = swap_used_mb(), contention()
    w = Whisper()
    w.load()
    out = {"whisper_load_s": round(w.load_s, 3), "contention": cont, "voices": {}}
    for f in sorted(OUT.glob("*/synth.json")):
        res = json.loads(f.read_text())
        rows, errs_s, errs_e, asr_t, asr_audio = [], [], [], 0.0, 0.0
        tot_ref = tot_err = nb_ref = nb_err = 0
        heard, brand_scenes, brand_ok = [], 0, 0
        for sc in res["scenes"]:
            wav = f.parent / sc["wav"]
            t0 = time.perf_counter()
            text, words = w.transcribe(wav)            # no prompt: an honest intelligibility test
            asr_t += time.perf_counter() - t0
            asr_audio += sc["duration"]
            ref, hyp = _norm_words(sc["spoken"]), _norm_words(text)
            e, subs = wer(ref, hyp)
            tot_ref += len(ref); tot_err += round(e * len(ref))
            brand_ref = [x for x in ref if x.startswith("shro")]
            nb_ref += len(ref) - len(brand_ref)
            nb_err += sum(1 for a, b in subs if not (a.startswith("shro") or b.startswith("shro")))
            if brand_ref:
                brand_scenes += 1
                h = _brand_heard(text)
                heard.append({"scene": sc["scene"], "asr": text, "brand_heard": h})
                brand_ok += bool(h)
            # timing: native word boundaries vs Whisper word timestamps on the same audio
            try:
                wb = [Boundary(**b) for b in sc["spoken_boundaries"]]
                aw = align(sc["spoken"], w.word_boundaries(wav, prompt=sc["spoken"]), sc["duration"], max_interp_frac=1.0)
                for nb, ab in zip(wb, aw):
                    if not ab.interpolated:
                        errs_s.append(abs(nb.start - ab.start)); errs_e.append(abs(nb.end - ab.end))
            except Exception as ex:  # noqa: BLE001 - recorded, not fatal
                heard.append({"scene": sc["scene"], "timing_compare_error": str(ex)})
            rows.append({"scene": sc["scene"], "asr": text, "wer": round(e, 3),
                         "errors": [s for s in subs][:12]})
        def q(xs, p):
            return round(sorted(xs)[min(len(xs) - 1, int(p * len(xs)))], 3) if xs else None
        out["voices"][res["tag"]] = {
            "wer": round(tot_err / max(1, tot_ref), 3), "wer_non_brand": round(nb_err / max(1, nb_ref), 3),
            "brand_scenes": brand_scenes, "brand_recognised": brand_ok, "brand_heard": heard,
            "native_vs_whisper_start_ms": {"median": q([x * 1000 for x in errs_s], .5), "p90": q([x * 1000 for x in errs_s], .9),
                                           "n": len(errs_s)},
            "native_vs_whisper_end_ms": {"median": q([x * 1000 for x in errs_e], .5), "p90": q([x * 1000 for x in errs_e], .9)},
            "asr_rtf": round(asr_t / max(1e-9, asr_audio), 3), "scenes": rows}
    out["peak_rss_mb"] = round(rss_mb())
    out["swap_delta_mb"] = round(swap_used_mb() - swap0, 1)
    w.unload()
    (OUT / "asr.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


# ---------------------------------------------------------------------------------------------
def _speech_edges(x, sr, thr_db=-35.0, frame=0.005):
    """(first, last) sample above threshold relative to the clip peak."""
    import numpy as np
    f = int(frame * sr)
    n = len(x) // f
    e = np.sqrt((x[: n * f].reshape(n, f) ** 2).mean(1) + 1e-12)
    on = np.nonzero(20 * np.log10(e / e.max()) > thr_db)[0]
    return (on[0] * f, (on[-1] + 1) * f) if len(on) else (0, len(x))


def synthetic() -> dict:
    """Ground truth by construction: each word synthesized alone (Kokoro af_heart), silence-trimmed by
    energy, concatenated with known gaps. Whisper word timestamps are then compared to the known
    boundaries. Also: native durations vs energy edges at the natural pauses of real sentences."""
    import random

    import numpy as np

    from .. import tts
    from ..timing import align, tokenize
    from . import pronunciation as P
    from .asr import Whisper, decode16k
    from .engines import KOKORO_SR, write_wav
    prov = tts.get_provider("kokoro")
    prov.load()
    rnd = random.Random(7)
    sents = [s["narration"] for s in scenes()]
    words = [t for s in sents for t in P.prepare(s, _pron()).spoken_tokens]
    words = [re.sub(r"[^\w'’]", "", w) for w in words][:60]
    style = prov.style("af_heart")
    pieces, truth, t = [np.zeros(int(0.3 * KOKORO_SR), np.float32)], [], 0.3
    for w in words:
        a, _ = prov._run(prov.phonemize(w, "en-us"), style, 1.0)
        s0, s1 = _speech_edges(a, KOKORO_SR)
        seg = a[s0:s1]
        truth.append((w, t, t + len(seg) / KOKORO_SR))
        gap = rnd.uniform(0.05, 0.35)
        pieces += [seg, np.zeros(int(gap * KOKORO_SR), np.float32)]
        t += len(seg) / KOKORO_SR + gap
    wav = OUT / "synthetic-known-boundaries.wav"
    audio = np.concatenate(pieces)
    write_wav(wav, audio, KOKORO_SR)
    # native durations vs energy at real pauses (af_heart, real narration)
    nat = []
    for s in sents:
        sp = P.prepare(s, _pron()).spoken
        a, phs = prov._run(" ".join(prov.phonemize(sp, "en-us").split()), style, 1.05)
        from .native import words_from_phonemes
        toks = tokenize(sp)
        try:
            b, _ = words_from_phonemes(toks, phs)
        except ValueError:
            b, _ = words_from_phonemes(toks, phs, [prov.phonemize(re.sub(r"[^\w'’-]", "", x) or x, "en-us") for x in toks])
        # energy-based speech onset of the whole utterance vs first-word start; offset vs last-word end
        s0, s1 = _speech_edges(a, KOKORO_SR)
        nat.append((b[0].start - s0 / KOKORO_SR, b[-1].end - s1 / KOKORO_SR))
    prov.unload()
    w = Whisper(); w.load()
    _, hyp = w.transcribe(wav)
    from ..tts import Boundary
    al = align(" ".join(x[0] for x in truth), [Boundary(h.text, h.start, h.end) for h in hyp], len(audio) / KOKORO_SR,
               max_interp_frac=1.0)
    es = [abs(a.start - tr[1]) * 1000 for a, tr in zip(al, truth) if not a.interpolated]
    ee = [abs(a.end - tr[2]) * 1000 for a, tr in zip(al, truth) if not a.interpolated]
    w.unload()
    def q(xs, p):
        return round(sorted(xs)[min(len(xs) - 1, int(p * len(xs)))], 1) if xs else None
    res = {"words": len(truth), "matched": len(es),
           "whisper_start_err_ms": {"median": q(es, .5), "p90": q(es, .9), "max": q(es, 1.0)},
           "whisper_end_err_ms": {"median": q(ee, .5), "p90": q(ee, .9), "max": q(ee, 1.0)},
           "within_50ms_start": round(sum(e <= 50 for e in es) / max(1, len(es)), 3),
           "within_100ms_start": round(sum(e <= 100 for e in es) / max(1, len(es)), 3),
           "native_utterance_onset_minus_energy_ms": [round(a * 1000, 1) for a, _ in nat],
           "native_utterance_offset_minus_energy_ms": [round(b * 1000, 1) for _, b in nat],
           "audio": wav.name, "decode_check_samples": int(len(decode16k(wav)))}
    (OUT / "synthetic.json").write_text(json.dumps(res, indent=1))
    return res


# ---------------------------------------------------------------------------------------------
def _pauses(sc_rows) -> dict:
    gaps, punct_gaps = [], []
    for r in sc_rows:
        b = r["spoken_boundaries"]
        for a, c in zip(b, b[1:]):
            g = c["start"] - a["end"]
            (punct_gaps if a["text"][-1] in ".,?!" else gaps).append(g)
    def q(xs, p):
        return round(sorted(xs)[min(len(xs) - 1, int(p * len(xs)))] * 1000) if xs else None
    return {"intra_median_ms": q(gaps, .5), "intra_p90_ms": q(gaps, .9), "intra_over_150ms": sum(g > .15 for g in gaps),
            "punct_median_ms": q(punct_gaps, .5), "punct_max_ms": q(punct_gaps, 1.0)}


def report() -> str:
    from . import registry
    asr = json.loads((OUT / "asr.json").read_text()) if (OUT / "asr.json").exists() else {"voices": {}}
    for a in asr["voices"].values():   # recompute brand detection from the stored transcripts
        for h in a.get("brand_heard", []):
            if "asr" in h:
                h["brand_heard"] = _brand_heard(h["asr"])
        a["brand_recognised"] = sum(bool(h.get("brand_heard")) for h in a.get("brand_heard", []) if "asr" in h)
    syn = json.loads((OUT / "synthetic.json").read_text()) if (OUT / "synthetic.json").exists() else None
    rows = []
    for f in sorted(OUT.glob("*/synth.json")):
        r = json.loads(f.read_text())
        a = asr["voices"].get(r["tag"], {})
        meta = registry.voices(r["provider"]).get(r["voice"], {})
        disp = sum(len(s["words"]) for s in r["scenes"])
        spk = sum(len(s["spoken_boundaries"]) for s in r["scenes"])
        speech = sum(s["spoken_boundaries"][-1]["end"] - s["spoken_boundaries"][0]["start"] for s in r["scenes"])
        p = _pauses(r["scenes"])
        methods = sorted({s["timing_method"] for s in r["scenes"]})
        val_err = sum(len(s["validation"]["errors"]) for s in r["scenes"])
        rows.append({"tag": r["tag"], "accent": meta.get("accent"), "gender": meta.get("gender"),
                     "licence": meta.get("licence"), "grade": meta.get("author_grade", "-"),
                     "load_s": r["load_s"], "rtf": r["rtf"], "peak_rss_mb": r["peak_rss_mb"],
                     "swap_delta_mb": r["swap_delta_mb"], "narration_s": r["narration_s"],
                     "disp_wps": round(disp / speech, 2), "spoken_wps": round(spk / speech, 2),
                     "wer": a.get("wer"), "wer_nb": a.get("wer_non_brand"),
                     "brand": f"{a.get('brand_recognised', '?')}/{a.get('brand_scenes', '?')}",
                     "nvw_start_med": (a.get("native_vs_whisper_start_ms") or {}).get("median"),
                     "nvw_start_p90": (a.get("native_vs_whisper_start_ms") or {}).get("p90"),
                     "methods": "+".join(methods), "val_errors": val_err, **p,
                     "contention": r["contention"]})
    (OUT / "summary.json").write_text(json.dumps({"rows": rows, "synthetic": syn, "whisper": {
        k: asr.get(k) for k in ("whisper_load_s", "peak_rss_mb", "swap_delta_mb", "contention")}}, indent=1))
    hdr = ("| voice | accent | lic | grade* | load s | RTF | peak RSS MB | swap Δ MB | narr s | words/s (disp/spoken) "
           "| WER | WER non-brand | brand heard | native-vs-whisper start ms (med/p90) | pauses intra med/p90 ms | timing |")
    lines = [hdr, "|" + "---|" * hdr.count("|")[:-1] if False else "|" + "|".join(["---"] * (hdr.count("|") - 1)) + "|"]
    for r in rows:
        lines.append(f"| {r['tag']} | {r['accent']} {r['gender'][0] if r['gender'] else ''} | {r['licence']} | {r['grade']} "
                     f"| {r['load_s']} | {r['rtf']} | {r['peak_rss_mb']} | {r['swap_delta_mb']} | {r['narration_s']} "
                     f"| {r['disp_wps']}/{r['spoken_wps']} | {r['wer']} | {r['wer_nb']} | {r['brand']} "
                     f"| {r['nvw_start_med']}/{r['nvw_start_p90']} | {r['intra_median_ms']}/{r['intra_p90_ms']} | {r['methods']} |")
    md = "\n".join(lines)
    (OUT / "RESULTS.md").write_text("# Voice evaluation results\n\nGenerated by `python -m pipeline.voice.evaluate`. "
                                    "*grade = the Kokoro author's own grade (VOICES.md), not measured here.\n\n" + md + "\n\n"
                                    + "Synthetic known-boundary test (Whisper base.en word timestamps vs truth):\n\n```\n"
                                    + json.dumps(syn, indent=1) + "\n```\n")
    return md


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    py = [sys.executable, "-m", "pipeline.voice.evaluate"]
    for p, v, lang in candidates():
        if (OUT / tag(p, v, lang) / "synth.json").exists() and "--force" not in sys.argv:
            continue
        print(f"== {tag(p, v, lang)}", flush=True)
        subprocess.run(py + ["synth", p, v] + ([lang] if lang else []), check=True, cwd=ROOT)
    print("== asr", flush=True)
    subprocess.run(py + ["asr"], check=True, cwd=ROOT)
    print("== synthetic", flush=True)
    subprocess.run(py + ["synthetic"], check=True, cwd=ROOT)
    print(report())


if __name__ == "__main__":  # pragma: no cover
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("VIDEO_PIPELINE_TTS_INPROCESS", "1")   # measure the engine in this process
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "synth":
        r = synth(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
        print(json.dumps({k: v for k, v in r.items() if k != "scenes"}))
    elif cmd == "asr":
        asr_eval()
    elif cmd == "synthetic":
        print(json.dumps(synthetic(), indent=1))
    elif cmd == "report":
        print(report())
    else:
        run()
