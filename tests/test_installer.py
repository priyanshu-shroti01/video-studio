"""install.sh and bin/videostudio: syntax, lint, dry-run, resume markers, safe code updates, launcher status.

Nothing here installs, downloads or starts anything: the installer only runs with --dry-run (or is sourced to test
its helper functions on temp folders), and the launcher only runs `status`, `help` and an unknown command.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
LAUNCHER = ROOT / "bin" / "videostudio"

STEPS = [
    "Checking your Mac",
    "Homebrew",
    "Tools: ffmpeg",
    "Downloading Video Studio",
    "Installing the video engine",
    "Downloading the browser",
    "Installing the Python parts",
    "Downloading the voices",
    "Downloading the local AI writing model",
    "Building the sound effects kit",
    "Building the Studio app",
    "Adding the videostudio command",
]

ACTIONS = [  # README Quick start, in order
    "would run: npm ci --legacy-peer-deps",
    "would run: npx --yes remotion browser ensure",
    "would run: uv sync",
    "would run: uv run python -m pipeline.voice.registry fetch",
    "would run: uv run python -m pipeline.intelligence runtime start",
    "would run: ollama pull ",
    "would run: uv run python -m pipeline.intelligence runtime stop",
    "would run: bash scripts/sound-layer.sh kit",
    "would run: uv run python -m studio.build",
    "would link ",
]


def _env(home: Path, **extra: str) -> dict[str, str]:
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SHELL": "/bin/zsh",
           "LANG": "en_US.UTF-8"}
    env.update(extra)
    return env


def _tree(p: Path) -> list[str]:
    return sorted(str(x.relative_to(p)) for x in p.rglob("*"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bash(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=60)


# ------------------------------------------------------------------------------------------- syntax / lint

@pytest.mark.parametrize("script", [INSTALL, LAUNCHER], ids=["install.sh", "videostudio"])
def test_bash_syntax(script):
    assert script.exists()
    assert os.access(script, os.X_OK), f"{script.name} should be executable"
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("script", [INSTALL, LAUNCHER], ids=["install.sh", "videostudio"])
def test_shellcheck(script):
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck not installed")
    r = subprocess.run(["shellcheck", "-s", "bash", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ------------------------------------------------------------------------------------------------ dry run

def _check_dry_run_output(out: str) -> None:
    pos = []
    for i, title in enumerate(STEPS, 1):
        needle = f"[{i}/{len(STEPS)}] {title}"
        assert needle in out, f"missing step {needle!r} in:\n{out}"
        pos.append(out.index(needle))
    assert pos == sorted(pos), "steps out of order"
    apos = [out.index(a) for a in ACTIONS]
    assert apos == sorted(apos), f"actions out of order:\n{out}"
    assert "Dry run finished: nothing was installed or changed." in out


def test_dry_run_prints_steps_in_order_and_creates_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    real_home = Path(os.path.expanduser("~"))
    before = {p: p.exists() for p in (real_home / "VideoStudio", real_home / ".local/bin/videostudio")}
    r = subprocess.run(["bash", str(INSTALL), "--dry-run"], env=_env(home), capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    _check_dry_run_output(r.stdout)
    assert str(home / "VideoStudio") in r.stdout          # default install folder follows $HOME
    assert _tree(home) == [], "dry run must not create files"
    assert _tree(tmp_path) == ["home"]
    assert {p: p.exists() for p in before} == before, "dry run touched the real home folder"


def test_dry_run_env_var_and_piped_like_curl(tmp_path):
    """`curl … | bash` reads the script from stdin; VIDEOSTUDIO_DRY_RUN=1 is the same as --dry-run."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "custom place"
    r = subprocess.run(["bash"], input=INSTALL.read_text(), capture_output=True, text=True, timeout=60,
                       env=_env(home, VIDEOSTUDIO_DRY_RUN="1", VIDEOSTUDIO_HOME=str(target)))
    assert r.returncode == 0, r.stdout + r.stderr
    _check_dry_run_output(r.stdout)
    assert f"Installing into: {target}" in r.stdout
    assert _tree(tmp_path) == ["home"]


def test_unknown_option_is_rejected(tmp_path):
    r = subprocess.run(["bash", str(INSTALL), "--bogus"], env=_env(tmp_path), capture_output=True, text=True)
    assert r.returncode == 2
    assert "Unknown option" in r.stderr
    assert _tree(tmp_path) == []


def test_dry_run_skips_steps_with_a_matching_marker(tmp_path):
    home = tmp_path / "home"
    markers = home / "VideoStudio/.pipeline/install"
    markers.mkdir(parents=True)
    # The model step's key is the model name; without the code downloaded the installer uses its fallback.
    model = next(line.split('"')[1] for line in INSTALL.read_text().splitlines()
                 if line.startswith("DEFAULT_LLM_MODEL="))
    (markers / "model.done").write_text(model + "\n")
    (markers / "studio.done").write_text("an-older-version\n")      # stale key: must run again
    r = subprocess.run(["bash", str(INSTALL), "--dry-run"], env=_env(home), capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    model_part = r.stdout.split("[9/12]")[1].split("[10/12]")[0]
    assert "Already done, skipping." in model_part
    assert "ollama pull" not in model_part
    studio_part = r.stdout.split("[11/12]")[1].split("[12/12]")[0]
    assert "would run: uv run python -m studio.build" in studio_part
    assert sorted(p.name for p in markers.iterdir()) == ["model.done", "studio.done"]


def test_dry_run_reruns_steps_whose_output_is_gone(tmp_path):
    """The browser lives in node_modules (wiped by `npm ci`) and the voices in models/: a marker alone is not
    enough. The Python step's key includes the pinned Python version (an older marker without it reruns)."""
    home = tmp_path / "home"
    app = home / "VideoStudio"
    markers = app / ".pipeline/install"
    markers.mkdir(parents=True)
    (app / ".venv").mkdir()
    py = next(line.split('"')[1] for line in INSTALL.read_text().splitlines() if line.startswith("DEFAULT_PYTHON="))
    # Without the code downloaded, file_key gives "none": these markers match the keys of this dry run.
    for name in ("browser", "voices"):
        (markers / f"{name}.done").write_text("none\n")
    (markers / "uv.done").write_text(f"none-py{py}\n")
    r = subprocess.run(["bash", str(INSTALL), "--dry-run"], env=_env(home), capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would run: npx --yes remotion browser ensure" in r.stdout.split("[6/12]")[1].split("[7/12]")[0]
    assert "Already done, skipping." in r.stdout.split("[7/12]")[1].split("[8/12]")[0]
    assert "registry fetch" in r.stdout.split("[8/12]")[1].split("[9/12]")[0]
    (markers / "uv.done").write_text("none\n")                       # marker from before the Python pin
    r = subprocess.run(["bash", str(INSTALL), "--dry-run"], env=_env(home), capture_output=True, text=True,
                       timeout=60)
    assert "would run: uv sync" in r.stdout.split("[7/12]")[1].split("[8/12]")[0]


def test_python_is_pinned_for_uv(tmp_path):
    """uv would otherwise pick the newest Python on the Mac (Homebrew's ollama brings python@3.15, which
    onnxruntime has no wheels for). Installer and launcher must agree on the version."""
    py = next(line.split('"')[1] for line in INSTALL.read_text().splitlines() if line.startswith("DEFAULT_PYTHON="))
    assert 'export UV_PYTHON="${VIDEOSTUDIO_PYTHON:-$DEFAULT_PYTHON}"' in INSTALL.read_text()
    assert f'export UV_PYTHON="${{VIDEOSTUDIO_PYTHON:-{py}}}"' in LAUNCHER.read_text()


# ------------------------------------------------------------------------- helper functions (sourced)

def _source(app_home: Path, body: str) -> subprocess.CompletedProcess:
    script = f'source "{INSTALL}"\nAPP_HOME="{app_home}"\nDRY_RUN=0\nLOG=/dev/null\n{body}\n'
    return _bash(script, _env(app_home.parent))


def test_sourcing_does_not_run_main(tmp_path):
    r = _source(tmp_path / "VS", "echo sourced-ok")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "sourced-ok"
    assert _tree(tmp_path) == []


def test_marker_resume_logic(tmp_path):
    app = tmp_path / "VS"
    r = _source(app, """
step_done npm k1 && echo "fresh:done" || echo "fresh:todo"
mark_done npm k1
step_done npm k1 && echo "same:done" || echo "same:todo"
step_done npm k2 && echo "newkey:done" || echo "newkey:todo"
step_done npm k1 node_modules/.bin/remotion && echo "missing:done" || echo "missing:todo"
mkdir -p "$APP_HOME/node_modules/.bin" && touch "$APP_HOME/node_modules/.bin/remotion"
step_done npm k1 node_modules/.bin/remotion && echo "present:done" || echo "present:todo"
ran=0; f() { ran=$((ran+1)); }
resumable npm k1 "" f; echo "ran=$ran"
resumable npm k3 "" f; echo "ran=$ran"
cat "$APP_HOME/.pipeline/install/npm.done"
DRY_RUN=1; resumable voices v1 "" f; [ -e "$APP_HOME/.pipeline/install/voices.done" ] && echo dry:marked || echo dry:none
""")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.split()
    for expected in ("fresh:todo", "same:done", "newkey:todo", "missing:todo", "present:done", "ran=0", "ran=1",
                     "k3", "dry:none"):
        assert expected in lines, f"{expected} not in {lines}"


def test_optional_step_failure_warns_and_required_step_failure_stops(tmp_path):
    app = tmp_path / "VS"
    r = _source(app, 'bad() { return 1; }\nresumable soundkit c1 "" bad optional\necho after-optional\n'
                     'resumable npm k1 "" bad\necho never')
    assert r.returncode == 1
    assert "after-optional" in r.stdout and "never" not in r.stdout
    assert "Run the same install command again" in r.stdout
    assert not (app / ".pipeline/install/soundkit.done").exists()


def test_update_keeps_user_data_and_replaces_code(tmp_path):
    app, staging = tmp_path / "VS", tmp_path / "staging"
    files_new = {
        "pyproject.toml": "new",
        "pipeline/cli.py": "new code",
        "brands/acme/brand.json": "upstream brand",
        "brands/newbrand/brand.json": "upstream new brand",
        "projects/acme/briefs/a.json": "upstream brief",
        "knowledge/acme/facts.json": "upstream facts",
        "public/shared/assets.json": "new shared",
        "public/brands/acme/logo.svg": "upstream logo",
        "audio/music/library.json": "upstream library",
        ".gitignore": "new ignore",
    }
    files_old = {
        "pyproject.toml": "old",
        "pipeline/cli.py": "old code",
        "pipeline/removed.py": "stale module",
        "brands/acme/brand.json": "USER brand",
        "projects/acme/briefs/a.json": "USER brief",
        "projects/acme/briefs/mine.json": "USER only",
        "knowledge/acme/facts.json": "USER facts",
        "output/productions/P1/video.mp4": "USER video",
        "video-out/acme/v.mp4": "USER copy",
        ".pipeline/registry.db": "USER db",
        "public/shared/assets.json": "old shared",
        "public/brands/acme/logo.svg": "USER logo",
        "audio/music/library.json": "USER library",
        "audio/kit/catalog.json": "generated kit",
        "node_modules/x/index.js": "deps",
        "models/voice/kokoro.onnx": "model",
    }
    for base, files in ((staging, files_new), (app, files_old)):
        for rel, text in files.items():
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_text(text)
    r = _source(app, f'merge_tree "{staging}" "$APP_HOME" ""')
    assert r.returncode == 0, r.stdout + r.stderr

    def text(rel):
        return (app / rel).read_text()

    # code: replaced (stale files in code folders go away)
    assert text("pyproject.toml") == "new"
    assert text("pipeline/cli.py") == "new code"
    assert not (app / "pipeline/removed.py").exists()
    assert text("public/shared/assets.json") == "new shared"
    assert text(".gitignore") == "new ignore"
    # user data: never replaced, missing upstream files added
    assert text("brands/acme/brand.json") == "USER brand"
    assert text("brands/newbrand/brand.json") == "upstream new brand"
    assert text("projects/acme/briefs/a.json") == "USER brief"
    assert text("projects/acme/briefs/mine.json") == "USER only"
    assert text("knowledge/acme/facts.json") == "USER facts"
    assert text("output/productions/P1/video.mp4") == "USER video"
    assert text("video-out/acme/v.mp4") == "USER copy"
    assert text(".pipeline/registry.db") == "USER db"
    assert text("public/brands/acme/logo.svg") == "USER logo"
    assert text("audio/music/library.json") == "USER library"
    # generated / downloaded folders that are not in the download: untouched
    assert text("audio/kit/catalog.json") == "generated kit"
    assert text("node_modules/x/index.js") == "deps"
    assert text("models/voice/kokoro.onnx") == "model"


def test_backup_user_data(tmp_path):
    app = tmp_path / "VS"
    (app / "brands/acme").mkdir(parents=True)
    (app / "brands/acme/brand.json").write_text("{}")
    (app / "projects").mkdir()
    r = _source(app, "backup_user_data")
    assert r.returncode == 0, r.stdout + r.stderr
    backups = list((app / ".pipeline/backups").glob("user-data-*.tar.gz"))
    assert len(backups) == 1
    listing = subprocess.run(["tar", "-tzf", str(backups[0])], capture_output=True, text=True).stdout
    assert "brands/acme/brand.json" in listing


def test_sound_tool_is_refetched_only_when_the_pinned_commit_changed(tmp_path):
    app = tmp_path / "VS"
    sl = app / "skills/opus-sound-layer"
    body = 'DRY_RUN=1\ndo_soundkit | grep -c "would download the sound tool" || true'

    def downloads() -> bool:
        r = _source(app, body)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout.strip() == "1"

    assert downloads()                                              # not there yet
    (sl / "scripts").mkdir(parents=True)
    (sl / "scripts/sfx.py").write_text("")
    assert not downloads()                                          # a copy without a marker: a developer's clone
    (sl / ".installed-commit").write_text("0000000\n")
    assert downloads()                                              # installed by an older installer: update it
    commit = next(line.split('"')[1] for line in INSTALL.read_text().splitlines()
                  if line.startswith("SOUND_LAYER_COMMIT="))
    (sl / ".installed-commit").write_text(commit + "\n")
    assert not downloads()


def test_backup_user_data_keeps_only_the_newest(tmp_path):
    app = tmp_path / "VS"
    (app / "brands").mkdir(parents=True)
    backups = app / ".pipeline/backups"
    backups.mkdir(parents=True)
    old = [f"user-data-2026010{i}-000000.tar.gz" for i in range(1, 8)]
    for name in old:
        (backups / name).write_text("old")
    r = _source(app, "backup_user_data")
    assert r.returncode == 0, r.stdout + r.stderr
    left = sorted(p.name for p in backups.iterdir())
    assert len(left) == 5
    assert left[:4] == old[-4:]                                       # the oldest are removed first
    assert left[4].startswith("user-data-") and left[4] not in old  # the new one is kept


# ---------------------------------------------------------------------------------------------- launcher

def _launcher(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = _env(home, VIDEOSTUDIO_HOME=str(home / "VideoStudio"), VIDEOSTUDIO_PORT=str(_free_port()),
               VIDEOSTUDIO_NO_BROWSER="1")
    return subprocess.run([str(LAUNCHER), *args], env=env, capture_output=True, text=True, timeout=30)


def test_launcher_status_not_running(tmp_path):
    r = _launcher(tmp_path, "status")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "not running" in r.stdout
    assert _tree(tmp_path) == []


def test_launcher_stale_pid_file_is_not_trusted(tmp_path):
    state = tmp_path / "VideoStudio/.pipeline/studio"
    state.mkdir(parents=True)
    (state / "studio.pid").write_text(f"{os.getpid()}\n")      # alive, but not a Studio process
    r = _launcher(tmp_path, "status")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "not running" in r.stdout


def test_launcher_help_and_unknown_command(tmp_path):
    r = _launcher(tmp_path, "help")
    assert r.returncode == 0
    for sub in ("videostudio stop", "videostudio status", "videostudio update", "videostudio doctor",
                "videostudio logs"):
        assert sub in r.stdout
    r = _launcher(tmp_path, "frobnicate")
    assert r.returncode == 2
    assert "Unknown command" in r.stdout


def test_launcher_without_install_explains(tmp_path):
    r = _launcher(tmp_path, "doctor")
    assert r.returncode == 1
    assert "not installed" in r.stdout and "install.sh" in r.stdout
    assert _tree(tmp_path) == []


def test_launcher_resolves_home_through_symlink(tmp_path):
    """~/.local/bin/videostudio is a symlink; the launcher finds its install folder from the link target."""
    app = tmp_path / "VS"
    (app / "bin").mkdir(parents=True)
    shutil.copy2(LAUNCHER, app / "bin/videostudio")
    (app / "pyproject.toml").write_text("")
    link = tmp_path / "bin/videostudio"
    link.parent.mkdir()
    link.symlink_to(app / "bin/videostudio")
    state = app / ".pipeline/studio"
    state.mkdir(parents=True)
    (state / "studio.log").write_text("hello from the log\n")
    env = _env(tmp_path, VIDEOSTUDIO_PORT=str(_free_port()))
    r = subprocess.run([str(link), "logs"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "hello from the log" in r.stdout
    assert "studio.log" in r.stdout


def test_download_and_update_from_a_local_tarball(tmp_path):
    """download_code end to end, offline: file:// tarball (GitHub layout: one top folder), install, then update."""
    src = tmp_path / "src/video-studio-main"
    for rel, text in {"pyproject.toml": "v1", "install.sh": "#!/bin/bash\n", "bin/videostudio": "#!/bin/bash\n",
                      "brands/acme/brand.json": "upstream"}.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    tarball = tmp_path / "main.tar.gz"
    subprocess.run(["tar", "-czf", str(tarball), "-C", str(src.parent), src.name], check=True)
    app = tmp_path / "VS"
    run = f'export VIDEOSTUDIO_TARBALL_URL="file://{tarball}"\ndownload_code\necho "key=$VERSION_KEY"'
    r = _source(app, run)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (app / "pyproject.toml").read_text() == "v1"
    assert os.access(app / "bin/videostudio", os.X_OK)
    assert not (app / ".pipeline/install/download").exists()       # staging cleaned up
    assert not (app / ".pipeline/backups").exists()                # first install: nothing to back up
    (app / "brands/acme/brand.json").write_text("USER edit")
    (src / "pyproject.toml").write_text("v2")
    subprocess.run(["tar", "-czf", str(tarball), "-C", str(src.parent), src.name], check=True)
    r = _source(app, run)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (app / "pyproject.toml").read_text() == "v2"
    assert (app / "brands/acme/brand.json").read_text() == "USER edit"
    assert len(list((app / ".pipeline/backups").glob("user-data-*.tar.gz"))) == 1


def test_download_refuses_to_overwrite_a_git_checkout(tmp_path):
    app = tmp_path / "VS"
    (app / ".git").mkdir(parents=True)
    (app / "pyproject.toml").write_text("dev")
    r = _source(app, 'export VIDEOSTUDIO_TARBALL_URL="file:///nonexistent"\ndownload_code')
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Git checkout" in r.stdout
    assert (app / "pyproject.toml").read_text() == "dev"
