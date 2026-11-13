"""Local TTS worker process (see engines.WorkerProvider). One JSON request per stdin line, one JSON
result per stdout line. Exits on EOF (parent closed the pipe, died, or the idle timer fired)."""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    os.environ["VIDEO_PIPELINE_TTS_INPROCESS"] = "1"
    from ..errors import PipelineError
    from . import engines
    out = sys.stdout
    sys.stdout = sys.stderr  # stray prints from libraries must not corrupt the protocol
    provs: dict = {}
    for line in sys.stdin:
        try:
            req = json.loads(line)
            p = provs.get(req["provider"]) or provs.setdefault(req["provider"], engines.make(req["provider"]))
            bounds = p.synthesize(req["text"], req["voice"], req["rate"], req["pitch"], req["out"], 0,
                                  options=req.get("options") or None)
            res = {"ok": True, "bounds": [b.__dict__ for b in bounds], "info": p.last_info}
        except PipelineError as e:
            res = {"ok": False, "error": e.message, "detail": e.detail, "transient": e.transient, "code": e.code}
        except Exception as e:  # noqa: BLE001 - reported to the parent, which raises TTSError
            res = {"ok": False, "error": f"{type(e).__name__}: {e}", "transient": False}
        out.write(json.dumps(res, default=float) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
