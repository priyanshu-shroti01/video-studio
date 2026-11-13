"""LLM provider interface: `generate_json(...)` against a JSON schema, with timeout, retries and unload.

Providers
  ollama  local Ollama server (127.0.0.1 only). Structured output via `format: <json schema>`, model unloaded
          after use (`keep_alive`), memory guard before every load, remote/cloud models refused.
  mock    deterministic, for tests and offline runs (no model needed).

Privacy: briefs, scripts and project data only ever go to a loopback address. `OllamaProvider` refuses
non-loopback hosts and any model the server reports as remote (e.g. `*:cloud`)."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..errors import PipelineError
from ..paths import ROOT
from ..system import mem_snapshot

DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_HOST = "http://127.0.0.1:11434"
RUNTIME_DIR = ROOT / "models" / "llm" / "runtime"      # pid + server log (git-ignored)
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
# Environment for an Ollama server we start ourselves: loopback only, no cloud, never prune the
# user's existing blobs, one model at a time, unload immediately unless a request asks otherwise.
SERVER_ENV = {
    "OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_NO_CLOUD": "1", "OLLAMA_NOPRUNE": "1", "OLLAMA_KEEP_ALIVE": "0",
    "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_CONTEXT_LENGTH": "8192",
}


class LLMError(PipelineError):
    code = "LLM_FAILED"


class LLMUnavailable(LLMError):
    """Runtime not installed / not running / model not pulled / not enough memory. Callers fall back to
    the deterministic planner."""
    code = "LLM_UNAVAILABLE"


class LLMOutputInvalid(LLMError):
    code = "LLM_OUTPUT_INVALID"


@dataclass
class GenStats:
    provider: str
    model: str
    wall_s: float = 0.0
    load_s: float = 0.0
    prompt_tokens: int = 0
    prompt_s: float = 0.0
    output_tokens: int = 0
    output_s: float = 0.0
    attempts: int = 1
    mem_before_mb: float | None = None

    @property
    def tokens_per_s(self) -> float | None:
        return round(self.output_tokens / self.output_s, 2) if self.output_s > 0 else None

    def as_dict(self) -> dict:
        d = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}
        d["tokens_per_s"] = self.tokens_per_s
        return d


@dataclass
class GenResult:
    data: dict
    raw: str
    stats: GenStats
    schema_errors: list[str] = field(default_factory=list)


class Provider:
    name = "base"
    model = ""

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def generate_json(self, *, system: str, messages: list[dict], schema: dict, task: str, context: dict | None = None,
                      temperature: float = 0.7, seed: int | None = None, max_tokens: int = 1500,
                      timeout: float = 240.0, retries: int = 1, keep_alive: str | int = "30s") -> GenResult:
        raise NotImplementedError

    def unload(self) -> None:
        pass

    def info(self) -> dict:
        return {"provider": self.name, "model": self.model}


def check_output(data, schema: dict) -> list[str]:
    from .jsonschema import check
    return check(data, schema, "$")


# ---------------------------------------------------------------------------------------------
class MockProvider(Provider):
    """Deterministic provider. `responder(task, context, messages) -> dict` decides the output; by default
    the intelligence package's own deterministic planner answers (so the LLM code path is exercised end to
    end without a model). `script` (a list of dicts/strings) is replayed first, for tests of repair loops."""
    name = "mock"

    def __init__(self, responder=None, script: list | None = None, model: str = "mock-1"):
        self.responder, self.script, self.model = responder, list(script or []), model
        self.calls: list[dict] = []

    def generate_json(self, *, system, messages, schema, task, context=None, temperature=0.7, seed=None,
                      max_tokens=1500, timeout=240.0, retries=1, keep_alive="30s") -> GenResult:
        self.calls.append({"task": task, "context": context, "messages": messages})
        if self.script:
            out = self.script.pop(0)
        elif self.responder:
            out = self.responder(task, context or {}, messages)
        else:
            from .mock_responses import default_response
            out = default_response(task, context or {}, messages)
        raw = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMOutputInvalid(f"mock output is not JSON: {e}") from e
        st = GenStats(self.name, self.model, wall_s=0.0, output_tokens=len(raw) // 4)
        return GenResult(data, raw, st, check_output(data, schema))


# ---------------------------------------------------------------------------------------------
def _http(url: str, payload: dict | None = None, timeout: float = 10.0) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - loopback only (checked by caller)
        return json.loads(r.read().decode() or "{}")


def ollama_binary() -> str | None:
    return shutil.which("ollama") or next((p for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama")
                                           if Path(p).exists()), None)


class OllamaRuntime:
    """Start/stop a loopback-only Ollama server on demand. Only stops a server it started (pid file)."""

    def __init__(self, host: str = DEFAULT_HOST):
        self.host = host.rstrip("/")
        u = urlparse(self.host)
        if u.hostname not in LOOPBACK:
            raise LLMError(f"refusing non-loopback Ollama host {self.host!r}: briefs must stay on this machine")
        self.pidfile = RUNTIME_DIR / "ollama.pid"
        self.logfile = RUNTIME_DIR / "ollama-serve.log"

    def version(self) -> str | None:
        try:
            return _http(f"{self.host}/api/version", timeout=2).get("version")
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def running(self) -> bool:
        return self.version() is not None

    def start(self, wait: float = 20.0) -> dict:
        if self.running():
            return {"started": False, "already_running": True, "version": self.version()}
        exe = ollama_binary()
        if not exe:
            raise LLMUnavailable("Ollama is not installed (brew install ollama); using the deterministic planner instead")
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, **SERVER_ENV}
        log = open(self.logfile, "ab")
        p = subprocess.Popen([exe, "serve"], env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        self.pidfile.write_text(str(p.pid))
        t0 = time.time()
        while time.time() - t0 < wait:
            if self.running():
                return {"started": True, "pid": p.pid, "version": self.version(), "startup_s": round(time.time() - t0, 2)}
            if p.poll() is not None:
                break
            time.sleep(0.25)
        raise LLMUnavailable(f"Ollama server did not come up (see {self.logfile})")

    def stop(self) -> dict:
        if not self.pidfile.exists():
            return {"stopped": False, "reason": "not started by the pipeline (no pid file); leaving it alone"}
        pid = int(self.pidfile.read_text().strip() or 0)
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        self.pidfile.unlink(missing_ok=True)
        return {"stopped": True, "pid": pid}

    def status(self) -> dict:
        v = self.version()
        out = {"host": self.host, "installed": bool(ollama_binary()), "binary": ollama_binary(), "running": v is not None,
               "version": v, "started_by_pipeline": self.pidfile.exists()}
        if v:
            try:
                out["loaded"] = [{"name": m["name"], "size_vram": m.get("size_vram"), "size": m.get("size")}
                                 for m in _http(f"{self.host}/api/ps", timeout=3).get("models", [])]
                out["models"] = [{"name": m["name"], "size": m.get("size"), "format": m.get("details", {}).get("format"),
                                  "remote": bool(m.get("remote_host"))} for m in _http(f"{self.host}/api/tags", timeout=3)["models"]]
            except (urllib.error.URLError, OSError, KeyError, ValueError):
                pass
        return out


def ollama_processes() -> list[dict]:
    """pid/rss of every ollama process (server + model runners), for peak-RSS sampling."""
    out = subprocess.run(["ps", "-axo", "pid=,rss=,command="], capture_output=True, text=True).stdout
    procs = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and "ollama" in parts[2].split()[0]:
            procs.append({"pid": int(parts[0]), "rss_mb": int(parts[1]) / 1024, "cmd": parts[2][:120]})
    return procs


class RSSSampler:
    """Background sampler of the summed RSS of all ollama processes."""

    def __init__(self, interval: float = 0.2):
        self.interval, self.peak_mb, self._stop = interval, 0.0, threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            self.peak_mb = max(self.peak_mb, sum(p["rss_mb"] for p in ollama_processes()))
            self._stop.wait(self.interval)

    def __enter__(self):
        self._t.start(); return self

    def __exit__(self, *a):
        self._stop.set(); self._t.join(timeout=2)


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, *, autostart: bool = True,
                 required_mb: float | None = None, headroom_mb: float = 400.0, num_ctx: int = 6144):
        self.runtime = OllamaRuntime(host)
        self.model, self.host, self.autostart, self.num_ctx = model, self.runtime.host, autostart, num_ctx
        from .registry import model_entry
        ent = model_entry(model) or {}
        self.required_mb = required_mb if required_mb is not None else float(ent.get("memory_required_mb") or 3200)
        self.headroom_mb = headroom_mb
        self._loaded = False

    # -- checks ----------------------------------------------------------------------------
    def _model_meta(self) -> dict:
        tags = _http(f"{self.host}/api/tags", timeout=5).get("models", [])
        m = next((t for t in tags if t["name"] == self.model or t.get("model") == self.model), None)
        if m is None:
            raise LLMUnavailable(f"model {self.model!r} is not pulled (ollama pull {self.model})")
        if m.get("remote_host") or self.model.endswith(":cloud") or "-cloud" in self.model:
            raise LLMError(f"model {self.model!r} runs on a remote host ({m.get('remote_host')}); refusing to send project data")
        return m

    def available(self) -> tuple[bool, str]:
        if not ollama_binary() and not self.runtime.running():
            return False, "Ollama is not installed"
        if not self.runtime.running():
            if not self.autostart:
                return False, "Ollama server is not running"
            try:
                self.runtime.start()
            except LLMError as e:
                return False, e.message
        try:
            self._model_meta()
        except LLMError as e:
            return False, e.message
        except (urllib.error.URLError, OSError) as e:
            return False, f"Ollama API error: {e}"
        return True, "ok"

    def memory_guard(self) -> dict:
        """Refuse to load when reclaimable memory is below the model's measured need (+ headroom) or when a
        different model is already resident (never two large models at once)."""
        loaded = _http(f"{self.host}/api/ps", timeout=5).get("models", [])
        others = [m["name"] for m in loaded if m["name"] != self.model]
        for name in others:   # unload, don't stack
            _http(f"{self.host}/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
        if any(m["name"] == self.model for m in loaded):
            return {"already_loaded": True, "unloaded_others": others}
        snap = mem_snapshot()
        need = self.required_mb + self.headroom_mb
        if snap.available_mb < need:
            raise LLMUnavailable(
                f"not enough reclaimable memory to load {self.model}: {snap.available_mb:.0f} MB available, "
                f"{need:.0f} MB needed (model {self.required_mb:.0f} + headroom {self.headroom_mb:.0f}); swap in use "
                f"{snap.swap_used_mb:.0f} MB. Close apps or wait for the render to finish.")
        return {"available_mb": round(snap.available_mb), "needed_mb": round(need), "unloaded_others": others}

    # -- generation ------------------------------------------------------------------------
    def generate_json(self, *, system, messages, schema, task, context=None, temperature=0.7, seed=None,
                      max_tokens=1500, timeout=240.0, retries=1, keep_alive="30s") -> GenResult:
        ok, why = self.available()
        if not ok:
            raise LLMUnavailable(why)
        guard = self.memory_guard()
        payload = {
            "model": self.model, "stream": False, "format": schema, "keep_alive": keep_alive, "think": False,
            "messages": [{"role": "system", "content": system}, *messages],
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": self.num_ctx,
                        **({"seed": seed} if seed is not None else {})},
        }
        last: Exception | None = None
        for attempt in range(1, retries + 2):
            t0 = time.time()
            try:
                r = _http(f"{self.host}/api/chat", payload, timeout=timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = LLMError(f"Ollama request failed: {e}", transient=True)
                time.sleep(min(2 * attempt, 6))
                continue
            self._loaded = True
            raw = r.get("message", {}).get("content", "")
            st = GenStats(self.name, self.model, wall_s=time.time() - t0, load_s=r.get("load_duration", 0) / 1e9,
                          prompt_tokens=r.get("prompt_eval_count", 0), prompt_s=r.get("prompt_eval_duration", 0) / 1e9,
                          output_tokens=r.get("eval_count", 0), output_s=r.get("eval_duration", 0) / 1e9, attempts=attempt,
                          mem_before_mb=guard.get("available_mb"))
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                last = LLMOutputInvalid(f"model output is not valid JSON ({e.msg} at {e.pos}); "
                                        f"done_reason={r.get('done_reason')}", detail=raw[-400:])
                continue
            return GenResult(data, raw, st, check_output(data, schema))
        raise last or LLMError("generation failed")

    def unload(self) -> None:
        try:
            _http(f"{self.host}/api/generate", {"model": self.model, "keep_alive": 0}, timeout=30)
        except (urllib.error.URLError, OSError):
            pass
        self._loaded = False

    def info(self) -> dict:
        return {"provider": self.name, "model": self.model, "host": self.host, "required_mb": self.required_mb}


def get_provider(name: str | None = None, **kw) -> Provider:
    """`name`: 'ollama' | 'mock' | None (env VIDEO_LLM_PROVIDER, default 'ollama')."""
    name = name or os.environ.get("VIDEO_LLM_PROVIDER", "ollama")
    if name == "mock":
        return MockProvider(**kw)
    if name == "ollama":
        return OllamaProvider(**kw)
    raise LLMError(f"unknown LLM provider {name!r} (use 'ollama' or 'mock')")
