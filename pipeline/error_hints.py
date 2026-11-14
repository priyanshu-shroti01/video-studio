"""Error catalogue: known failures -> one plain sentence a non-technical user can act on.

`explain(code, message, detail)` returns {"hint": str, "action": str | None} for the first matching rule, or
None. PipelineError.to_dict() (pipeline/errors.py) adds these two keys to every error the CLI, the job
registry and the Studio API serialise; the CLI prints the hint under the error.

`action` is a stable id from ACTIONS that the Studio can turn into a button; None when the fix is outside
the app (install something, edit a credentials setup). Rules match on the error code (None = any code) and a
regex over the message (and detail). Keep the hints short, concrete and free of jargon; docs/TROUBLESHOOTING.md
links here."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

# action id -> what the button does (labels for the UI; the Studio owns the wording on screen)
ACTIONS: dict[str, str] = {
    "rebuild-preview": "Build the preview again",
    "approve-preview": "Review and approve the preview",
    "edit-storyboard": "Open the storyboard editor",
    "fix-brief": "Edit the brief",
    "choose-brand": "Choose or add a brand",
    "retry": "Try again",
    "close-apps": "Close other apps, then try again",
    "free-disk": "Free up disk space",
    "start-ai": "Start the local AI model",
    "review-flags": "Open the review flags",
    "re-review": "Rebuild the package and review it again",
    "redraft-metadata": "Draft the titles and captions again",
    "check-account": "Check the connected account",
    "approve": "Review and approve the video",
}

# QA / preview-gate check ids -> plain words
CHECK_WORDS: dict[str, str] = {
    "audio.clipping": "the sound distorts (clipping)",
    "audio.duration": "the audio length doesn't match the video",
    "audio.loudness": "the loudness is off",
    "audio.sfx_placed": "sound effects are missing",
    "audio.silence": "there is unexpected silence",
    "audio.true_peak": "the sound is too loud at its peaks",
    "audio.voice_present": "the voice is missing",
    "brand.logo_aspect": "the logo is stretched",
    "brand.logo_present": "the logo is missing",
    "brand.no_duplicate_branding": "the logo appears twice",
    "brand.palette": "the colours are off-brand",
    "brand.watermark_render": "the watermark didn't render",
    "brand.watermark_safe": "the watermark is in an unsafe spot",
    "captions.ass_valid": "the caption file is broken",
    "captions.complete": "captions are missing words",
    "captions.no_overlap": "captions overlap",
    "captions.present": "captions are missing",
    "captions.reading_speed": "captions go by too fast to read",
    "captions.srt_valid": "the caption file is broken",
    "captions.within_audio": "captions run past the audio",
    "container.valid": "the video file is damaged",
    "decode.full": "the video file can't be played to the end",
    "file.exists": "the video file is missing",
    "file.nonempty": "the video file is empty",
    "layout.caption_band": "text sits where captions go",
    "layout.media_aspect": "an image is stretched",
    "layout.safe_area": "text is outside the safe area",
    "layout.text_overflow": "text overflows its box",
    "layout.overflow": "text overflows its box",
    "ocr.engine": "the text-recognition engine (OCR) didn't run",
    "ocr.footage_labels": "labels on screen recordings can't be read",
    "ocr.no_template_labels": "placeholder text is on screen",
    "ocr.prices_urls_exact": "prices or web addresses on screen aren't readable",
    "ocr.titles_legible": "titles aren't readable",
    "stream.audio": "the audio track is missing or wrong",
    "stream.video": "the video track is missing or wrong",
    "sync.av_offset": "the voice is out of sync with the picture",
    "sync.narration_visual": "the screen stays still while the voice talks",
    "video.aspect": "the video shape is wrong",
    "video.codec": "the video format is wrong",
    "video.color_tags": "the colour settings are wrong",
    "video.duration": "the video length is wrong",
    "video.fps": "the frame rate is wrong",
    "video.resolution": "the resolution is wrong",
    "visual.black_frames": "there are black frames",
    "visual.blank_scenes": "a scene is blank",
    "visual.branding": "the branding check failed",
    "visual.caption_safe_area": "captions are outside the safe area",
    "visual.frozen": "the picture freezes",
    "visual_qa.run": "the visual checks couldn't run",
    "preview.empty_scenes": "a scene is empty",
    "preview.repetition": "scenes look the same",
    "storyboard.backdrop_rhythm": "backgrounds repeat too much",
    "storyboard.hero_visual": "a scene has no main visual",
    "storyboard.invented_labels": "there is made-up price text",
    "storyboard.narration_sync": "the screen stays still while the voice talks, or a number shows before it is said",
    "storyboard.numbers_verified": "a number on screen isn't a verified fact",
    "storyboard.variety": "the scenes lack variety",
}

# brief field -> how a marketer would call it
BRIEF_FIELDS: dict[str, str] = {
    "brand": "Brand", "product": "Product", "price": "Price", "audience": "Audience", "format": "Format",
    "formats": "Formats", "duration_seconds": "Length (duration_seconds)", "goal": "Goal", "cta": "Call to action",
    "tone": "Tone", "voice": "Voice", "request": "Request", "provider": "Provider", "engine": "Engine",
    "url": "Web address", "notes": "Notes", "requirements": "Requirements", "components": "Components",
}

_TYPE_WORDS = {"integer": "a whole number", "number": "a number", "string": "text", "boolean": "true or false",
               "array": "a list", "object": "a group of fields"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _join(words: list[str]) -> str:
    words = list(dict.fromkeys(w for w in words if w))
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def check_words(ids: list[str]) -> str:
    """['short:ocr.engine', 'visual.black_frames'] -> 'the text-recognition engine (OCR) didn't run and ...'"""
    out = []
    for i in ids:
        cid = i.split(":", 1)[-1].strip()
        out.append(CHECK_WORDS.get(cid, cid))
    return _join(out)


def _ids_from(message: str, detail: str | None) -> list[str]:
    if detail:
        try:
            v = json.loads(detail)
            if isinstance(v, list):
                return [str(x) for x in v]
        except ValueError:
            pass
        ids = [ln.split(":", 1)[0].strip() for ln in detail.splitlines() if ":" in ln]
        if ids:
            return ids
    return re.findall(r"'([\w-]+:[\w.]+)'", message)


def brief_problem(line: str) -> str:
    """'$brief.duration_seconds: 5 < minimum 10' -> 'Length (duration_seconds) must be at least 10.'"""
    m = re.match(r"\s*\$[\w]*((?:\.[\w-]+|\[\d+\])*):\s*(.*)$", line)
    if not m:
        return line.strip()
    path, msg = m.group(1).lstrip("."), m.group(2)
    field = re.split(r"[.\[]", path)[0] if path else ""
    label = BRIEF_FIELDS.get(field, field or "The brief")
    if (r := re.match(r"missing required '([\w-]+)'", msg)):
        return f"{BRIEF_FIELDS.get(r.group(1), r.group(1))} is missing."
    if (r := re.match(r"unknown field '([\w-]+)'", msg)):
        return f"'{r.group(1)}' is not a brief field; remove it or check the spelling."
    if (r := re.match(r".* not one of \[(.*)\]", msg)):
        return f"{label} must be one of: {r.group(1).replace(chr(39), '')}."
    if (r := re.match(r".* < minimum (\S+)", msg)):
        return f"{label} must be at least {r.group(1)}."
    if (r := re.match(r".* > maximum (\S+)", msg)):
        return f"{label} must be at most {r.group(1)}."
    if (r := re.match(r"longer than (\d+)", msg)):
        return f"{label} is too long (at most {r.group(1)} characters)."
    if (r := re.match(r"shorter than (\d+)", msg)):
        return f"{label} is too short (at least {r.group(1)} characters)."
    if (r := re.match(r"expected ([\w/]+), got (\w+)", msg)):
        want = " or ".join(_TYPE_WORDS.get(t, t) for t in r.group(1).split("/"))
        return f"{label} must be {want}."
    if (r := re.match(r"needs at least (\d+) items", msg)):
        return f"{label} needs at least {r.group(1)} entries."
    if "does not match" in msg:
        return f"{label} has an unexpected format."
    return f"{label}: {msg}"


# ---- rules -------------------------------------------------------------------------------------------
Hint = str | Callable[[re.Match, str, str | None], str]


@dataclass(frozen=True)
class Rule:
    codes: frozenset[str] | None     # None = any code
    pattern: re.Pattern
    hint: Hint
    action: str | None = None


def R(codes, pattern: str, hint: Hint, action: str | None = None) -> Rule:
    cs = None if codes is None else frozenset([codes] if isinstance(codes, str) else codes)
    return Rule(cs, re.compile(pattern, re.I | re.S), hint, action)


def _qa_failed(m, message, detail):
    ids = _ids_from(message, detail)
    what = check_words(ids) or "some checks"
    tail = " Text recognition usually stops when memory is very low: close other apps or restart the Mac, " \
           "then run the checks again." if any(i.endswith(("ocr.engine", "visual_qa.run")) for i in ids) \
        else " Open the QA report to see where, fix it, and render again."
    return f"The finished video failed its quality checks: {what}.{tail}"


def _qa_action(message, detail) -> str | None:
    ids = _ids_from(message, detail)
    return "retry" if any(i.endswith(("ocr.engine", "visual_qa.run")) for i in ids) else None


def _gate_failed(m, message, detail):
    what = check_words(_ids_from(message, detail)) or "some checks"
    return f"The preview didn't pass its quality checks: {what}. Fix the storyboard, then build the preview again."


def _brief_invalid(m, message, detail):
    probs = [brief_problem(ln) for ln in (detail or "").splitlines() if ln.strip()]
    if not probs:
        return "The brief has a problem. Check every field and try again."
    more = f" (and {_plural(len(probs) - 4, 'more problem')})" if len(probs) > 4 else ""
    return "The brief needs fixing: " + " ".join(probs[:4]) + more


def _known(text: str) -> str:
    """"['a', 'b']" -> "a, b", without hidden test brands."""
    names = re.findall(r"'([^']+)'", text)
    try:
        from .brands import is_hidden
        names = [n for n in names if not is_hidden(n)]
    except Exception:  # noqa: BLE001 - a hint must never fail
        pass
    return ", ".join(names)


RULES: list[Rule] = [
    # preview & approval of the preview -------------------------------------------------------------
    R(None, r"storyboard changed after the preview",
      "The storyboard changed after the preview. Build the preview again, then approve it.", "rebuild-preview"),
    R(None, r"no preview yet", "There is no preview yet. Build the preview first, then approve it.", "rebuild-preview"),
    R(None, r"preview has not been approved by a person",
      "A person must look at the preview and approve it before the video can be made. Open Preview & QA, "
      "check the pictures and the gate result, then approve.", "approve-preview"),
    R(None, r"preview quality gate FAILED", _gate_failed, "edit-storyboard"),
    R(None, r"preview approval needs a reviewer name", "Type your name as the reviewer, then approve the preview."),
    R(None, r"storyboard is locked while", "The storyboard can't be edited at this stage. Request changes on the "
      "video first to unlock it."),
    # QA ---------------------------------------------------------------------------------------------
    R("QA_FAILED", r"critical QA checks failed", _qa_failed),          # action computed in explain()
    R(None, r"swiftc not found", "Checking the text on screen needs Apple's Command Line Tools. Install them with "
      "`xcode-select --install`, then try again."),
    R(None, r"could not compile the OCR tool", "The text-recognition tool couldn't be built. Update Xcode Command "
      "Line Tools (`xcode-select --install`), then try again."),
    R(None, r"^OCR failed|visual QA could not run|OCR (?:engine )?(?:is )?(?:not responding|failing)",
      "Your Mac's text recognition (OCR) stopped working, usually because memory is very tight. Close other apps "
      "or restart the Mac, then try again.", "retry"),
    # brief, brand, config ---------------------------------------------------------------------------
    R("CONFIG_INVALID", r"brief is invalid", _brief_invalid, "fix-brief"),
    R("CONFIG_INVALID", r"brief must be a JSON object", "The brief file isn't in the right shape. Start from an "
      "example brief and fill in the fields.", "fix-brief"),
    R("CONFIG_INVALID", r"no brand given", "The brief doesn't say which brand it is for. Fill in Brand.", "fix-brief"),
    R("CONFIG_INVALID", r"no brand matches '?(?P<ref>[^';]+)'?; known brands: (?P<known>\[[^\]]*\])",
      lambda m, *_: f"No brand called '{m['ref']}' is set up. Pick one of: {_known(m['known']) or 'none yet'}, "
                    "or add the website as a new brand.", "choose-brand"),
    R("CONFIG_INVALID", r"'(?P<ref>[^']+)' matches several brands",
      lambda m, *_: f"'{m['ref']}' matches more than one brand. Choose the brand explicitly.", "choose-brand"),
    R("NOT_FOUND", r"unknown brand '?(?P<b>[^']+)'?",
      lambda m, *_: f"There is no brand '{m['b']}'. Choose one from the brand list or add it.", "choose-brand"),
    R("CONFIG_INVALID", r"no creative\.industry|brand profile .* not found",
      "This brand isn't fully set up yet (its creative settings are missing). Finish the brand setup first."),
    R("CONFIG_INVALID", r"no verified facts for brand",
      "This brand has no verified facts yet, so every price or claim would need review. Verify the brand's facts first."),
    R("CONFIG_INVALID", r"project config is invalid|storyboard is invalid",
      "The project settings have mistakes. Each one is listed below with the field it belongs to."),
    R(None, r"storyboard is invalid", "The storyboard has mistakes; each is listed below. Fix them in the storyboard "
      "editor and save again.", "edit-storyboard"),
    # local AI model ---------------------------------------------------------------------------------
    R("LLM_UNAVAILABLE", r"not enough reclaimable memory",
      "There isn't enough free memory to load the AI model. Close other apps or wait for the render to finish, "
      "then try again.", "close-apps"),
    R("LLM_UNAVAILABLE", r"Ollama is not installed",
      "The local AI model (Ollama) isn't installed. Install it with `brew install ollama`; until then the studio "
      "uses its built-in planner."),
    R("LLM_UNAVAILABLE", r"is not pulled \((?P<cmd>ollama pull [^)]+)\)",
      lambda m, *_: f"The AI model hasn't been downloaded yet. Download it once with `{m['cmd']}`, then try again."),
    R("LLM_UNAVAILABLE", r".", "The local AI model isn't running. Start it, then try again.", "start-ai"),
    R(("LLM_FAILED", "LLM_OUTPUT_INVALID"), r"non-loopback|remote host",
      "The AI model is set up to run on another computer; the studio only sends briefs to this Mac. Use a local model."),
    R(("LLM_FAILED", "LLM_OUTPUT_INVALID"), r".", "The AI model gave an answer the studio couldn't use. Try again.",
      "retry"),
    # resources --------------------------------------------------------------------------------------
    R(None, r"No space left on device|Errno 28|GB free on disk|disk (?:is )?full",
      "Your disk is almost full. Free up space (empty the Trash, or archive old videos), then try again.", "free-disk"),
    R("RESOURCES_INSUFFICIENT", r"MB memory available",
      "Your Mac is short on memory. Close other apps (and stop the AI model if it's running), then try again.",
      "close-apps"),
    R("RESOURCES_INSUFFICIENT", r"waited .* for its turn",
      "Another heavy job (a render or the AI model) is still running. Try again when it has finished.", "retry"),
    # render -----------------------------------------------------------------------------------------
    R("RENDER_FAILED", r"Remotion CLI not installed", "The video renderer isn't installed. Run `npm ci` in the "
      "studio folder, then try again."),
    R("RENDER_FAILED", r"Chromium headless shell is unavailable", "The renderer's browser couldn't be installed. "
      "Check the internet connection once, then try again.", "retry"),
    R(("RENDER_FAILED", "PROCESS_STALLED", "PROCESS_TIMEOUT"),
      r"Target closed|Protocol error|Page crashed|crash|Browser (?:has )?(?:closed|disconnected)|ECONNRESET|"
      r"socket hang up|SIGKILL|killed",
      "The video renderer (Chromium) crashed, usually because the Mac ran short of memory. Close other apps, "
      "then render again; finished parts are reused.", "retry"),
    R("ENCODER_FAILED", r".", "The Mac's video encoder failed. Render again; the studio falls back to the "
      "software encoder.", "retry"),
    R(("PROCESS_STALLED", "PROCESS_TIMEOUT"), r".", "A step stopped making progress. Try again; if it happens "
      "every time, a font or image in the video may be missing.", "retry"),
    R("RENDER_FAILED", r".", "The render failed. Try again; if it fails the same way, send the details below "
      "to whoever maintains the studio.", "retry"),
    # approval package -------------------------------------------------------------------------------
    R("APPROVAL_BLOCKED", r"package files changed since|not the current package|invalidated by a content change|"
      r"does not match the approved content hash|video changed during publishing|not part of the approved package",
      "A file in the reviewed package changed after it was reviewed, so the approval no longer counts. Rebuild the "
      "package and review it again.", "re-review"),
    R("APPROVAL_BLOCKED", r"blocking review flag",
      "Some review items still need a person's decision. Open the review flags, check each one, then approve.",
      "review-flags"),
    R("APPROVAL_BLOCKED", r"approval needs completed QA|QA status is",
      "The video hasn't passed its quality checks yet, so it can't be approved. Fix the failing checks first."),
    R("APPROVAL_BLOCKED", r"approval needs a named reviewer|needs a reviewer",
      "Type your name as the reviewer (and a note if asked), then try again."),
    # publishing -------------------------------------------------------------------------------------
    R("PUBLISH_ACCOUNT_MISMATCH", r".",
      "The connected login belongs to a different account than this brand expects, so nothing was uploaded. "
      "Reconnect the brand's own account (see Social setup).", "check-account"),
    R("PUBLISH_NOT_CONFIGURED", r".", "This brand has no account set up for that platform yet. Add it in the "
      "brand's publishing settings (see Social setup)."),
    R("APPROVAL_BLOCKED", r"publishing requires an explicit APPROVED decision|only an APPROVED production",
      "Only an approved video can be published. Review the video and approve it first.", "approve"),
    R("APPROVAL_BLOCKED", r"publishing requires explicit confirmation",
      "Publishing needs a clear confirmation from you. Confirm that you want to publish this video."),
    R("APPROVAL_BLOCKED", r"no approved Instagram caption|metadata\.json failed validation",
      "The titles and captions aren't ready. Request changes, draft them again, then approve again.",
      "redraft-metadata"),
    R("APPROVAL_BLOCKED", r"not publishable to Instagram Reels",
      "This video doesn't fit Instagram Reels (it must be the tall 9:16 version, 3 s to 15 min). Use the short "
      "format."),
    R("APPROVAL_BLOCKED", r"publishAt time has passed",
      "The scheduled publish time is in the past. Pick a new time and approve again.", "redraft-metadata"),
    R("METADATA_LOCKED", r".", "Titles and captions are part of the approved package and can't change now. "
      "Request changes to reopen the review first."),
    # jobs -------------------------------------------------------------------------------------------
    R("INVALID_STATE_TRANSITION", r"task is already running",
      "That step is already running for this video. Wait for it to finish."),
    R("DUPLICATE_JOB", r".", "This exact video is already being made (or was made). Open that job instead."),
    R("TTS_FAILED", r"timed out|network/service error", "The online voice service didn't answer. Check the internet "
      "connection and try again.", "retry"),
]


def explain(code: str | None, message: str, detail: str | None = None) -> dict | None:
    """First matching catalogue entry -> {"hint": str, "action": str | None}; None if nothing matches."""
    text = f"{message}\n{detail or ''}"
    for r in RULES:
        if r.codes is not None and code not in r.codes:
            continue
        m = r.pattern.search(message) or r.pattern.search(text)
        if not m:
            continue
        hint = r.hint(m, message, detail) if callable(r.hint) else r.hint
        action = _qa_action(message, detail) if code == "QA_FAILED" else r.action
        return {"hint": hint, "action": action}
    return None


def explain_exception(e: BaseException) -> dict | None:
    """Same for any exception (OSError 'No space left on device', ...); PipelineErrors use their own fields."""
    explain_fn = getattr(e, "explain", None)
    if callable(explain_fn):
        res = explain_fn()
        return res if res.get("hint") else None
    if isinstance(e, OSError) and e.errno == 28:
        return explain(None, "No space left on device")
    return explain(type(e).__name__, str(e))
