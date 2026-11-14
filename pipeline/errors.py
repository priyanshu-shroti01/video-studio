"""Typed errors. `transient` decides whether a retry can help (network blips, Chromium crashes),
as opposed to deterministic failures (bad config, corrupt input) that would fail again identically."""


class PipelineError(Exception):
    code = "PIPELINE_ERROR"
    transient = False
    exit_code = 1

    def __init__(self, message: str, *, detail: str | None = None, transient: bool | None = None,
                 hint: str | None = None, action: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        if transient is not None:
            self.transient = transient
        self._hint, self._action = hint, action     # explicit ones win over the catalogue (pipeline/error_hints.py)

    def explain(self) -> dict:
        """{"hint": plain sentence | None, "action": action id | None} for a non-technical user."""
        if self._hint:
            return {"hint": self._hint, "action": self._action}
        from .error_hints import explain
        found = explain(self.code, self.message, self.detail)
        return found or {"hint": None, "action": self._action}

    @property
    def hint(self) -> str | None:
        return self.explain()["hint"]

    @property
    def action(self) -> str | None:
        return self.explain()["action"]

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail, "transient": self.transient,
                **self.explain()}

    def cli_lines(self) -> list[str]:
        """What the CLI prints on stderr: the error, its detail (trimmed), then the plain hint."""
        lines = [f"error [{self.code}]: {self.message}"]
        if self.detail:
            lines.append("  " + self.detail.strip().replace("\n", "\n  ")[-3000:])
        if (h := self.hint):
            lines.append(f"hint: {h}")
        return lines


class ConfigError(PipelineError):
    code, exit_code = "CONFIG_INVALID", 2


class PathError(PipelineError):
    code, exit_code = "PATH_REJECTED", 2


class AssetError(PipelineError):
    code = "ASSET_INVALID"


class TTSError(PipelineError):
    code = "TTS_FAILED"


class TimingError(PipelineError):
    code = "TIMING_INVALID"


class RenderError(PipelineError):
    code = "RENDER_FAILED"


class EncoderError(RenderError):
    code = "ENCODER_FAILED"


class ProcessTimeout(PipelineError):
    code, transient = "PROCESS_TIMEOUT", True


class ProcessStalled(PipelineError):
    code, transient = "PROCESS_STALLED", True


class Cancelled(PipelineError):
    code, exit_code = "CANCELLED", 130


class ResourceError(PipelineError):
    code = "RESOURCES_INSUFFICIENT"


class StateError(PipelineError):
    code = "INVALID_STATE_TRANSITION"


class DuplicateJob(PipelineError):
    code, exit_code = "DUPLICATE_JOB", 5


class NotFound(PipelineError):
    code, exit_code = "NOT_FOUND", 4


class QAFailed(PipelineError):
    code, exit_code = "QA_FAILED", 3


class PreflightError(PipelineError):
    """Raised by pipeline/preflight.py before heavy work when the Mac can't do it right now."""
    code = "PREFLIGHT"
