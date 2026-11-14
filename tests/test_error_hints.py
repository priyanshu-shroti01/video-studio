"""Error catalogue (pipeline/error_hints.py): known failures get a plain hint + action id, everywhere errors
are serialised (to_dict) and printed (CLI)."""
import json

import pytest

from pipeline import error_hints as H
from pipeline.errors import ConfigError, NotFound, PipelineError, PreflightError, QAFailed, RenderError, ResourceError
from pipeline.intelligence.providers import LLMError, LLMUnavailable
from pipeline.productions import ApprovalError
from pipeline.social.brandcfg import AccountMismatch, NotConfigured


def _x(e: PipelineError) -> dict:
    d = e.to_dict()
    assert set(d) >= {"code", "message", "detail", "transient", "hint", "action"}
    return d


def test_storyboard_changed_after_preview():
    d = _x(PipelineError("the storyboard changed after the preview; re-run the preview before approving it"))
    assert d["hint"] == "The storyboard changed after the preview. Build the preview again, then approve it."
    assert d["action"] == "rebuild-preview"


def test_preview_not_approved_and_gate_failed():
    d = _x(PipelineError("the storyboard preview has not been approved by a person for this storyboard",
                         detail="run `production preview` ..."))
    assert d["action"] == "approve-preview" and "approve" in d["hint"]
    d = _x(PipelineError("the preview quality gate FAILED; fix the storyboard first",
                         detail="storyboard.numbers_verified: ₹99 not a fact\nlayout.overflow: scene 2"))
    assert "a number on screen isn't a verified fact" in d["hint"] and "overflows" in d["hint"]
    assert d["action"] == "edit-storyboard"


def test_qa_failed_names_checks_in_plain_words():
    fails = ["short:visual.black_frames", "short:ocr.prices_urls_exact", "short:audio.loudness"]
    d = _x(QAFailed(f"critical QA checks failed: {fails}", detail=json.dumps(fails)))
    assert "black frames" in d["hint"] and "prices or web addresses" in d["hint"] and "loudness" in d["hint"]
    assert "short:" not in d["hint"] and d["action"] is None


def test_qa_failed_on_ocr_engine_suggests_memory_and_retry():
    fails = ["short:ocr.engine"]
    d = _x(QAFailed(f"critical QA checks failed: {fails}", detail=json.dumps(fails)))
    assert "text-recognition" in d["hint"] and "close other apps" in d["hint"].lower()
    assert d["action"] == "retry"
    # without a JSON detail the ids are read from the message
    d = _x(QAFailed(f"critical QA checks failed: {fails}"))
    assert d["action"] == "retry"


def test_ocr_failure():
    d = _x(PipelineError("OCR failed", detail="Vision request failed"))
    assert d["action"] == "retry" and "restart" in d["hint"]
    assert "xcode-select" in _x(PipelineError("swiftc not found (install Xcode Command Line Tools) — OCR QA "
                                              "unavailable"))["hint"]


def test_invalid_brief_says_which_field_and_what_is_expected():
    from pipeline.intelligence.brief import parse_brief
    with pytest.raises(ConfigError) as ei:
        parse_brief({"brand": "x", "product": "Hosting", "duration_seconds": 5, "format": "reel", "colour": "red"})
    d = _x(ei.value)
    assert d["action"] == "fix-brief"
    assert "Length (duration_seconds) must be at least 10." in d["hint"]
    assert "Format must be one of: short, landscape" in d["hint"]
    assert "'colour' is not a brief field" in d["hint"]
    with pytest.raises(ConfigError) as ei:
        parse_brief({"brand": "x"})
    assert "Product is missing." in ei.value.hint
    with pytest.raises(ConfigError) as ei:
        parse_brief({"brand": "x", "product": "p", "duration_seconds": "30"})
    assert "must be a whole number" in ei.value.hint


@pytest.mark.parametrize("line,want", [
    ("$brief.product: longer than 120", "Product is too long (at most 120 characters)."),
    ("$brief.duration_seconds: 400 > maximum 180", "Length (duration_seconds) must be at most 180."),
    ("$brief.formats: needs at least 1 items", "Formats needs at least 1 entries."),
])
def test_brief_problem_lines(line, want):
    assert H.brief_problem(line) == want


def test_unknown_and_ambiguous_brand():
    from pipeline.brands import resolve_brand
    with pytest.raises(ConfigError) as ei:
        resolve_brand("no-such-site-zz")
    d = _x(ei.value)
    assert d["action"] == "choose-brand" and "'no-such-site-zz'" in d["hint"] and "[" not in d["hint"]
    d = _x(ConfigError("'acme' matches several brands ['a', 'b']; pass --brand <id>"))
    assert d["action"] == "choose-brand" and "more than one brand" in d["hint"]
    assert _x(NotFound("unknown brand 'zz'"))["action"] == "choose-brand"


def test_llm_unavailable_variants():
    assert _x(LLMUnavailable("Ollama server did not come up (see x.log)"))["action"] == "start-ai"
    d = _x(LLMUnavailable("model 'qwen3:4b' is not pulled (ollama pull qwen3:4b)"))
    assert "`ollama pull qwen3:4b`" in d["hint"]
    d = _x(LLMUnavailable("not enough reclaimable memory to load m: 900 MB available, 4000 MB needed"))
    assert d["action"] == "close-apps"
    assert "brew install ollama" in _x(LLMUnavailable("Ollama is not installed (brew install ollama); ..."))["hint"]
    assert _x(LLMError("model output was not JSON"))["action"] == "retry"


def test_render_and_chromium_crash():
    d = _x(RenderError("render failed on frames 0-299: chunk failed: Page crashed!", transient=True))
    assert "Chromium" in d["hint"] and d["action"] == "retry"
    assert "npm ci" in _x(RenderError("Remotion CLI not installed (run `npm ci`)"))["hint"]


def test_disk_full_and_memory():
    d = _x(ResourceError("only 1.2 GB free on disk; this job needs at least 2.0 GB"))
    assert d["action"] == "free-disk"
    assert _x(PipelineError("ffmpeg exited with 1", detail="[Errno 28] No space left on device"))["action"] == "free-disk"
    assert _x(ResourceError("only 600 MB memory available; close apps before rendering"))["action"] == "close-apps"
    assert H.explain_exception(OSError(28, "No space left on device"))["action"] == "free-disk"


@pytest.mark.parametrize("msg", [
    "package files changed since the approval package was built; rebuild and re-review",
    "the package you reviewed is not the current package (hash mismatch)",
    "approval is missing or was invalidated by a content change; re-review required",
    "video changed during publishing",
])
def test_approval_invalidated_by_a_changed_file(msg):
    d = _x(ApprovalError(msg))
    assert d["action"] == "re-review" and "changed" in d["hint"]


def test_publishing_refused():
    d = _x(AccountMismatch("the youtube credentials belong to account UC1 (Other), not brand b's account UC2; "
                           "refusing to publish"))
    assert d["action"] == "check-account" and "nothing was uploaded" in d["hint"]
    d = _x(ApprovalError("production is QA_COMPLETE: publishing requires an explicit APPROVED decision"))
    assert d["action"] == "approve"
    assert _x(NotConfigured("brand b has no publishing.accounts.youtube"))["hint"]


def test_explicit_hint_wins_and_unknown_errors_have_null_fields():
    d = _x(PreflightError("x", hint="Do this.", action="retry"))
    assert (d["hint"], d["action"]) == ("Do this.", "retry")
    d = _x(PipelineError("something nobody catalogued"))
    assert d["hint"] is None and d["action"] is None


def test_every_action_id_is_declared():
    for r in H.RULES:
        assert r.action is None or r.action in H.ACTIONS, r.action
    assert "retry" in H.ACTIONS


def test_cli_lines_and_v3_wrapper_print_the_hint(capsys):
    e = PipelineError("the storyboard changed after the preview; re-run the preview before approving it")
    lines = e.cli_lines()
    assert lines[0].startswith("error [PIPELINE_ERROR]") and lines[-1].startswith("hint: The storyboard changed")
    from argparse import Namespace

    from pipeline.cli_v3 import _with_hint

    def boom(a):
        raise e
    assert _with_hint(boom)(Namespace(json=False)) == e.exit_code
    err = capsys.readouterr().err
    assert "error [PIPELINE_ERROR]" in err and "hint: The storyboard changed" in err
    with pytest.raises(PipelineError):              # --json: cli.py prints to_dict() (with hint/action)
        _with_hint(boom)(Namespace(json=True))
