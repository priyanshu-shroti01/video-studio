"""Build the Studio frontend: studio/web/src -> studio/web/dist/app.{js,css} with esbuild.

    uv run python -m studio.build [--dev]

Uses node_modules/.bin/esbuild (a devDependency). Not called by the server."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "studio/web"


def build(dev: bool = False) -> int:
    esbuild = ROOT / "node_modules/.bin/esbuild"
    if not esbuild.exists():
        print("esbuild not found: run `npm install` (esbuild is a devDependency)", file=sys.stderr)
        return 2
    args = [str(esbuild), str(WEB / "src/main.tsx"), "--bundle", "--format=esm", "--target=es2022", "--jsx=automatic",
            f"--outfile={WEB / 'dist/app.js'}", "--external:/files/*", "--legal-comments=none", "--log-level=warning",
            f"--define:process.env.NODE_ENV=\"{'development' if dev else 'production'}\""]
    args += ["--sourcemap"] if dev else ["--minify"]
    return subprocess.run(args, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(build("--dev" in sys.argv[1:]))
