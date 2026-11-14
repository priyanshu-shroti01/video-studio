#!/usr/bin/env bash
# Video Studio installer for macOS (Apple silicon).
#
#   curl -fsSL https://raw.githubusercontent.com/priyanshu-shroti01/video-studio/main/install.sh | bash
#   curl -fsSL …/install.sh | bash -s -- --dry-run      # show every action, change nothing
#   bash install.sh [--dry-run] [--verbose]
#
# Safe to run again: it updates the code, skips finished steps (marker files in
# ~/VideoStudio/.pipeline/install/) and never overwrites your own files (output/, video-out/, projects/,
# brands/, knowledge/, .pipeline/, public/brands/, audio/music/). Docs: docs/INSTALL.md.
#
# Environment:
#   VIDEOSTUDIO_HOME          install folder (default ~/VideoStudio)
#   VIDEOSTUDIO_DRY_RUN=1     same as --dry-run
#   VIDEOSTUDIO_VERBOSE=1     same as --verbose (show every command's output, not only the log)
#   VIDEOSTUDIO_TARBALL_URL   where to download the code from (default: GitHub main branch)
#
# Everything lives in functions and `main` is called on the last line, so the whole script is read
# before anything runs (important when it is piped from curl).
set -euo pipefail

REPO_SLUG="priyanshu-shroti01/video-studio"
DEFAULT_TARBALL_URL="https://codeload.github.com/${REPO_SLUG}/tar.gz/refs/heads/main"
DEFAULT_LLM_MODEL="qwen3:4b-instruct-2507-q4_K_M"   # fallback; the real value is read from the downloaded code
# The sound kit tool (MIT) is a third-party project that is not vendored in this repo; pinned commit.
SOUND_LAYER_REPO="Bodila51/opus-sound-layer"
SOUND_LAYER_COMMIT="52ac266a24b7dfd3cd06a28c34d5af360a8d7586"
BREW_INSTALL_URL="https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
BREW_PACKAGES=(ffmpeg uv node ollama)

# Top-level folders that hold the user's own work: files already there are never replaced.
USER_DATA_DIRS=(output video-out projects brands knowledge .pipeline)
# Deeper folders with the same rule (inside folders that otherwise get code updates).
USER_DATA_SUBDIRS=(public/brands audio/music)
# Folders that mix code (updated) with user/generated files (kept): merged file by file, never wiped.
MERGE_DIRS=(public audio)

STEP_TOTAL=12
STEP_NO=0
DRY_RUN=0
VERBOSE=0
LOG=/dev/null
CURRENT_STEP=""
VERSION_KEY="none"

# ---------------------------------------------------------------------------------------------- output

say() { printf '%s\n' "$*"; [[ $LOG == /dev/null ]] || printf '%s\n' "$*" >>"$LOG"; }
warn() { say "  ! $*"; }
info() { say "      $*"; }

step() {
  STEP_NO=$((STEP_NO + 1))
  CURRENT_STEP="$1"
  say ""
  say "[$STEP_NO/$STEP_TOTAL] $1"
}

die() {
  say ""
  say "Something went wrong${CURRENT_STEP:+ during: $CURRENT_STEP}."
  [[ $# -gt 0 ]] && say "  $*"
  if [[ $LOG != /dev/null ]]; then
    say "  The full details are in this file: $LOG"
  fi
  say "  Nothing you made was changed. Run the same install command again to continue from this step."
  say "  If it fails again, send the file above to whoever helps you with Video Studio."
  DIED=1
  exit 1
}

# Unexpected failure (a command outside the helpers): still tell the user what to do.
on_exit() {
  local rc=$?
  if [[ $rc -ne 0 && -z ${DIED:-} && $rc -ne 2 ]]; then
    DIED=1
    die "The installer stopped unexpectedly (code $rc)."
  fi
}

# ----------------------------------------------------------------------------------- doing things

# x CMD...: run a command (output to the log; also on screen with --verbose), or print it in dry-run.
x() {
  if [[ $DRY_RUN == 1 ]]; then
    say "      [dry-run] would run: $*"
    return 0
  fi
  printf '\n$ %s\n' "$*" >>"$LOG"
  if [[ $VERBOSE == 1 ]]; then
    "$@" </dev/null 2>&1 | tee -a "$LOG"
  else
    "$@" </dev/null >>"$LOG" 2>&1
  fi
}

# xin DIR CMD...: x, run inside DIR.
xin() {
  local dir=$1
  shift
  if [[ $DRY_RUN == 1 ]]; then
    say "      [dry-run] would run (in $dir): $*"
    return 0
  fi
  (cd "$dir" && x "$@")
}

# long-running x with a "still working" line every 30 s on a real terminal.
xlong() {
  if [[ $DRY_RUN == 1 || $VERBOSE == 1 || ! -t 1 ]]; then
    x "$@"
    return
  fi
  local t0=$SECONDS tick rc=0
  (while sleep 30; do printf '      still working (%d min so far)...\n' $(((SECONDS - t0) / 60)); done) &
  tick=$!
  x "$@" || rc=$?
  kill "$tick" 2>/dev/null || true
  wait "$tick" 2>/dev/null || true
  return "$rc"
}

mkd() {
  if [[ $DRY_RUN == 1 ]]; then say "      [dry-run] would create folder: $1"; else mkdir -p "$1"; fi
}

have() { command -v "$1" >/dev/null 2>&1; }

# Is there a terminal we can ask the user's password on (curl | bash has no stdin, but /dev/tty works)?
have_tty() { (exec </dev/tty) 2>/dev/null; }

file_key() { # file_key DIR FILE...: short hash of the files that exist (or "none")
  local dir=$1 f found=()
  shift
  for f in "$@"; do [[ -f $dir/$f ]] && found+=("$dir/$f"); done
  if [[ ${#found[@]} -eq 0 ]]; then echo none; return; fi
  cat "${found[@]}" | shasum -a 256 | cut -c1-16
}

# --------------------------------------------------------------------------- resume (marker files)

marker_dir() { echo "$APP_HOME/.pipeline/install"; }

# step_done ID KEY [PATH]: finished before with the same KEY (and PATH, if given, still exists)?
step_done() {
  local f
  f="$(marker_dir)/$1.done"
  [[ -f $f ]] || return 1
  [[ "$(cat "$f")" == "$2" ]] || return 1
  [[ -z ${3:-} || -e $APP_HOME/$3 ]] || return 1
  return 0
}

mark_done() {
  [[ $DRY_RUN == 1 ]] && return 0
  mkdir -p "$(marker_dir)"
  printf '%s\n' "$2" >"$(marker_dir)/$1.done"
}

# resumable ID KEY CHECK_PATH FUNCTION [optional]: skip when done, else run FUNCTION and record it.
resumable() {
  local id=$1 key=$2 check=$3 fn=$4 optional=${5:-}
  if step_done "$id" "$key" "$check"; then
    info "Already done, skipping."
    return 0
  fi
  if "$fn"; then
    mark_done "$id" "$key"
    [[ $DRY_RUN == 1 ]] || info "Done."
  elif [[ $optional == optional ]]; then
    warn "This optional part did not finish (details: $LOG). Video Studio still works without it;"
    warn "run the install command again later to retry."
  else
    die
  fi
}

# ------------------------------------------------------------------------------- the steps

check_mac() {
  step "Checking your Mac"
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  if [[ $os != Darwin ]]; then
    if [[ $DRY_RUN == 1 ]]; then
      warn "This is not a Mac ($os); continuing only because this is a dry run."
    else
      die "Video Studio needs macOS. This computer runs $os."
    fi
  else
    info "macOS $(sw_vers -productVersion 2>/dev/null || echo '?')"
  fi
  if [[ $arch == arm64 ]]; then
    info "Apple silicon: good."
  else
    warn "This Mac has an Intel processor ($arch). Video Studio is made for Apple silicon (M1 or newer);"
    warn "it will install, but making videos will be slow."
  fi
  local parent free_gb
  parent="$APP_HOME"
  while [[ ! -d $parent ]]; do parent="$(dirname "$parent")"; done
  free_gb=$(df -Pk "$parent" | awk 'NR==2 {print int($4/1048576)}')
  if [[ ${free_gb:-0} -lt 10 ]]; then
    warn "Only ${free_gb} GB free on this disk. The install needs about 6 GB, videos need more."
  else
    info "${free_gb} GB free on the disk."
  fi
  info "Installing into: $APP_HOME"
}

brew_path() {
  if [[ -x /opt/homebrew/bin/brew ]]; then echo /opt/homebrew/bin/brew
  elif [[ -x /usr/local/bin/brew ]]; then echo /usr/local/bin/brew
  elif have brew; then command -v brew
  fi
}

# Add a line to a shell profile once (dry-run: only say so).
add_to_profile() {
  local file=$1 line=$2
  if [[ -f $file ]] && grep -qF "$line" "$file"; then return 0; fi
  if [[ $DRY_RUN == 1 ]]; then
    say "      [dry-run] would add to $file: $line"
    return 0
  fi
  printf '\n# Added by the Video Studio installer\n%s\n' "$line" >>"$file"
  PROFILE_CHANGED=1
}

install_homebrew() {
  step "Homebrew (the free Mac app installer that Video Studio uses for its tools)"
  local brew
  brew="$(brew_path)"
  if [[ -n $brew ]]; then
    info "Already installed."
  else
    info "Homebrew is not installed yet. Installing it now (this can take 5 to 15 minutes)."
    info "It will ask for your Mac password: the one you use to log in to this Mac."
    info "Nothing appears on screen while you type the password; that is normal. Press Return after it."
    info "If a window asks to install the \"command line developer tools\", click Install."
    if [[ $DRY_RUN == 1 ]]; then
      say "      [dry-run] would run: /bin/bash -c \"\$(curl -fsSL $BREW_INSTALL_URL)\""
    else
      local script
      script="$(curl -fsSL "$BREW_INSTALL_URL")" || die "Could not download the Homebrew installer. Check the internet connection."
      if have_tty; then
        /bin/bash -c "$script" </dev/tty || die "The Homebrew installer stopped."
      else
        NONINTERACTIVE=1 /bin/bash -c "$script" </dev/null || die "The Homebrew installer stopped."
      fi
      brew="$(brew_path)"
      [[ -n $brew ]] || die "Homebrew finished, but the brew command was not found."
    fi
  fi
  [[ -n $brew ]] && eval "$("$brew" shellenv)"
  brew=${brew:-/opt/homebrew/bin/brew}
  case ":$ORIGINAL_PATH:" in
    *":${brew%/brew}:"*) ;;
    *) add_to_profile "$HOME/.zprofile" "eval \"\$($brew shellenv)\"" ;;
  esac
}

install_tools() {
  step "Tools: ffmpeg (video), uv (Python), node (video engine), ollama (local AI)"
  local missing=() p
  for p in "${BREW_PACKAGES[@]}"; do
    if have "$p"; then
      info "$p: already installed."
    else
      missing+=("$p")
    fi
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    return 0
  fi
  info "Installing: ${missing[*]} (a few minutes)."
  if [[ $DRY_RUN == 1 ]]; then
    say "      [dry-run] would run: brew install ${missing[*]}"
    return 0
  fi
  have brew || die "Homebrew is not available, so ${missing[*]} cannot be installed."
  xlong brew install "${missing[@]}" || die "Homebrew could not install: ${missing[*]}."
  for p in "${missing[@]}"; do
    have "$p" || die "$p was installed but cannot be found. Open a new Terminal window and run the installer again."
  done
}

# copy_missing SRC DST: copy files from SRC that do not exist in DST yet (never replaces a file).
copy_missing() {
  local src=$1 dst=$2 rel
  mkdir -p "$dst"
  while IFS= read -r rel; do
    rel=${rel#./}
    [[ -z $rel || $rel == . ]] && continue
    if [[ -d $src/$rel && ! -L $src/$rel ]]; then
      mkdir -p "$dst/$rel" || return 1
    elif [[ ! -e $dst/$rel && ! -L $dst/$rel ]]; then
      mkdir -p "$(dirname "$dst/$rel")"
      cp -pP "$src/$rel" "$dst/$rel" || return 1
    fi
  done < <(cd "$src" && find . -mindepth 1)
}

in_list() { local n=$1 e; shift; for e in "$@"; do [[ $e == "$n" ]] && return 0; done; return 1; }

# merge_tree SRC DST PREFIX: put the new code from SRC into DST. User-data folders only get missing files;
# mixed folders are merged entry by entry; everything else (code) is replaced.
merge_tree() {
  local src=$1 dst=$2 prefix=$3 entry name relpath
  mkdir -p "$dst" || return 1
  for entry in "$src"/* "$src"/.[!.]* "$src"/..?*; do
    [[ -e $entry || -L $entry ]] || continue
    name=${entry##*/}
    relpath=$prefix$name
    if in_list "$relpath" "${USER_DATA_DIRS[@]}" "${USER_DATA_SUBDIRS[@]}"; then
      copy_missing "$entry" "$dst/$name" || return 1
    elif [[ -d $entry ]] && in_list "$relpath" "${MERGE_DIRS[@]}"; then
      merge_tree "$entry" "$dst/$name" "$relpath/" || return 1
    else
      rm -rf "${dst:?}/$name" || return 1
      cp -pPR "$entry" "$dst/$name" || return 1
    fi
  done
}

backup_user_data() {
  local ts dirs=() d
  for d in brands knowledge projects public/brands audio/music; do
    [[ -e $APP_HOME/$d ]] && dirs+=("$d")
  done
  [[ ${#dirs[@]} -eq 0 ]] && return 0
  ts="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$APP_HOME/.pipeline/backups"
  tar -czf "$APP_HOME/.pipeline/backups/user-data-$ts.tar.gz" -C "$APP_HOME" "${dirs[@]}"
  info "Backed up your brands, facts and projects to .pipeline/backups/user-data-$ts.tar.gz"
}

download_code() {
  step "Downloading Video Studio"
  local url=${VIDEOSTUDIO_TARBALL_URL:-$DEFAULT_TARBALL_URL}
  local dl="$APP_HOME/.pipeline/install/download"
  if [[ -d $APP_HOME/.git ]]; then
    warn "$APP_HOME is a Git checkout; the installer will not overwrite it. Update it with git instead."
    VERSION_KEY="git-$(date +%s)"
    return 0
  fi
  local updating=0
  [[ -f $APP_HOME/pyproject.toml ]] && updating=1
  if [[ $DRY_RUN == 1 ]]; then
    say "      [dry-run] would download: $url"
    say "      [dry-run] would unpack it into a temporary folder: $dl/staging"
    [[ $updating == 1 ]] && say "      [dry-run] would back up brands/, knowledge/, projects/ to $APP_HOME/.pipeline/backups/"
    say "      [dry-run] would copy the new code into $APP_HOME (your files in ${USER_DATA_DIRS[*]} ${USER_DATA_SUBDIRS[*]} are kept)"
    return 0
  fi
  rm -rf "$dl"
  mkdir -p "$dl/staging"
  info "From: $url"
  curl -fL --retry 3 --retry-delay 2 -sS -o "$dl/video-studio.tar.gz" "$url" >>"$LOG" 2>&1 \
    || die "Could not download Video Studio. Check the internet connection and try again."
  tar -xzf "$dl/video-studio.tar.gz" -C "$dl/staging" --strip-components 1 >>"$LOG" 2>&1 \
    || die "The download looks damaged. Run the install command again."
  [[ -f $dl/staging/pyproject.toml && -f $dl/staging/bin/videostudio ]] \
    || die "The download does not look like Video Studio (no pyproject.toml / bin/videostudio)."
  VERSION_KEY="$(shasum -a 256 "$dl/video-studio.tar.gz" | cut -c1-16)"
  if [[ $updating == 1 ]]; then
    info "Updating the existing install (your videos, projects and brands are kept)."
    backup_user_data >>"$LOG" 2>&1 || die "Could not back up your brands and projects before updating."
  fi
  merge_tree "$dl/staging" "$APP_HOME" "" >>"$LOG" 2>&1 || die "Could not copy the new files into $APP_HOME."
  chmod +x "$APP_HOME/bin/videostudio" "$APP_HOME/install.sh" 2>/dev/null || true
  rm -rf "$dl"
  info "Video Studio code is in $APP_HOME (version $VERSION_KEY)."
}

# -- resumable setup steps (README Quick start) --

do_npm() { xlong npm ci --legacy-peer-deps; }
do_browser() { xlong npx --yes remotion browser ensure; }
do_uv() { xlong uv sync --frozen; }
do_voices() { xlong uv run python -m pipeline.voice.registry fetch; }
do_model() {
  local rc=0
  x uv run python -m pipeline.intelligence runtime start || return 1
  xlong ollama pull "$LLM_MODEL" || rc=$?
  x uv run python -m pipeline.intelligence runtime stop || true
  return "$rc"
}
do_soundkit() {
  if [[ ! -f $APP_HOME/skills/opus-sound-layer/scripts/sfx.py ]]; then
    local url="https://codeload.github.com/$SOUND_LAYER_REPO/tar.gz/$SOUND_LAYER_COMMIT"
    if [[ $DRY_RUN == 1 ]]; then
      say "      [dry-run] would download the sound tool (MIT licence): $url"
      say "      [dry-run] would unpack it into $APP_HOME/skills/opus-sound-layer"
    else
      local tmp="$APP_HOME/.pipeline/install/sound-layer"
      rm -rf "$tmp" && mkdir -p "$tmp/src" || return 1
      x curl -fL --retry 3 -sS -o "$tmp/sl.tar.gz" "$url" || return 1
      x tar -xzf "$tmp/sl.tar.gz" -C "$tmp/src" --strip-components 1 || return 1
      mkdir -p "$APP_HOME/skills" && rm -rf "$APP_HOME/skills/opus-sound-layer" || return 1
      mv "$tmp/src" "$APP_HOME/skills/opus-sound-layer" || return 1
      rm -rf "$tmp"
    fi
  fi
  xlong bash scripts/sound-layer.sh kit
}
do_studio() { x uv run python -m studio.build; }

setup_steps() {
  local h=$APP_HOME
  if [[ $DRY_RUN == 0 ]]; then cd "$h"; fi

  step "Installing the video engine (about 5 minutes)"
  resumable npm "$(file_key "$h" package-lock.json package.json scripts/patch-remotion-loopback.mjs)" \
    node_modules/.bin/remotion do_npm

  step "Downloading the browser that draws the videos (about 150 MB)"
  resumable browser "$(file_key "$h" package-lock.json)" "" do_browser

  step "Installing the Python parts"
  resumable uv "$(file_key "$h" uv.lock pyproject.toml)" .venv do_uv

  step "Downloading the voices (about 840 MB)"
  resumable voices "$(file_key "$h" pipeline/voice/registry.json)" "" do_voices

  LLM_MODEL="$(sed -n 's/^DEFAULT_MODEL = "\(.*\)".*/\1/p' "$h/pipeline/intelligence/providers.py" 2>/dev/null | head -1 || true)"
  LLM_MODEL=${LLM_MODEL:-$DEFAULT_LLM_MODEL}
  step "Downloading the local AI writing model ($LLM_MODEL, about 2.5 GB)"
  resumable model "$LLM_MODEL" "" do_model

  step "Building the sound effects kit"
  resumable soundkit "$SOUND_LAYER_COMMIT" audio/kit/catalog.json do_soundkit optional

  step "Building the Studio app"
  resumable studio "$VERSION_KEY" studio/web/dist/app.js do_studio
}

install_command() {
  step "Adding the videostudio command"
  local bindir="$HOME/.local/bin" target="$APP_HOME/bin/videostudio"
  mkd "$bindir"
  if [[ $DRY_RUN == 1 ]]; then
    say "      [dry-run] would link $bindir/videostudio -> $target"
  else
    [[ -f $target ]] || die "The launcher $target is missing."
    chmod +x "$target"
    ln -sfn "$target" "$bindir/videostudio"
  fi
  # shellcheck disable=SC2016  # $HOME/$PATH are meant to be expanded by the shell profile, not here
  local line='export PATH="$HOME/.local/bin:$PATH"'
  case ":$ORIGINAL_PATH:" in
    *":$bindir:"*) ;;
    *)
      add_to_profile "$HOME/.zprofile" "$line"
      [[ ${SHELL:-} == */bash ]] && add_to_profile "$HOME/.bash_profile" "$line"
      ;;
  esac
  [[ $DRY_RUN == 1 ]] || info "Installed: $bindir/videostudio"
}

finish() {
  CURRENT_STEP=""
  say ""
  if [[ $DRY_RUN == 1 ]]; then
    say "Dry run finished: nothing was installed or changed."
    return 0
  fi
  say "Video Studio is installed."
  say ""
  if [[ ${PROFILE_CHANGED:-0} == 1 ]]; then
    say "  1. Close this Terminal window and open a new one (so the new command is found)."
    say "  2. Type:  videostudio   and press Return. The Studio opens in your browser."
  else
    say "  Type:  videostudio   and press Return. The Studio opens in your browser."
  fi
  say ""
  say "  Later:  videostudio stop  |  videostudio update  |  videostudio doctor"
  say "  Your videos are saved in $APP_HOME/video-out"
  say "  Install log: $LOG"
}

usage() {
  sed -n 2,18p "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null | sed 's/^# \{0,1\}//' || true
  echo "Usage: install.sh [--dry-run] [--verbose]"
}

main() {
  local a
  for a in "$@"; do
    case "$a" in
      --dry-run|-n) DRY_RUN=1 ;;
      --verbose|-v) VERBOSE=1 ;;
      --help|-h) usage; return 0 ;;
      *) echo "Unknown option: $a (try --help)" >&2; return 2 ;;
    esac
  done
  [[ ${VIDEOSTUDIO_DRY_RUN:-0} == 1 ]] && DRY_RUN=1
  [[ ${VIDEOSTUDIO_VERBOSE:-0} == 1 ]] && VERBOSE=1
  [[ -n ${HOME:-} ]] || { echo "HOME is not set" >&2; return 1; }
  APP_HOME="${VIDEOSTUDIO_HOME:-$HOME/VideoStudio}"
  APP_HOME="${APP_HOME%/}"
  PROFILE_CHANGED=0
  ORIGINAL_PATH=$PATH
  trap on_exit EXIT
  # Tools installed earlier but not yet on PATH in this shell.
  export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

  say "Video Studio installer"
  if [[ $DRY_RUN == 1 ]]; then
    say "DRY RUN: every action is printed and nothing is executed, downloaded or written."
  else
    mkdir -p "$APP_HOME/.pipeline/install/logs"
    LOG="$APP_HOME/.pipeline/install/logs/install-$(date +%Y%m%d-%H%M%S).log"
    : >"$LOG"
    say "A detailed log is written to: $LOG"
  fi

  check_mac
  install_homebrew
  install_tools
  download_code
  setup_steps
  install_command
  finish
}

# Run main only when executed (bash install.sh, curl | bash), not when sourced by the tests.
if [[ -z ${BASH_SOURCE[0]:-} || ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
