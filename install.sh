#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${LATERAL_REPO_URL:-https://github.com/MauroProto/lateral.git}"
BRANCH="${LATERAL_BRANCH:-main}"
INSTALL_DIR="${LATERAL_INSTALL_DIR:-$HOME/.lateral-mode/source}"
VENV_DIR="${LATERAL_VENV_DIR:-$HOME/.lateral-mode/venv}"
BIN_DIR="${LATERAL_BIN_DIR:-$HOME/.local/bin}"

log() {
  printf 'lateral: %s\n' "$*"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'lateral: missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

need_cmd git

find_python() {
  candidates=()
  if [ -n "${PYTHON:-}" ]; then
    candidates+=("$PYTHON")
  fi
  candidates+=(python3.12 python3.11 python3.10 python3)

  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
      then
        command -v "$candidate"
        return 0
      fi
    fi
  done

  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  printf 'lateral: Python >= 3.10 is required. Install python3.10+ and rerun this installer.\n' >&2
  exit 1
fi

mkdir -p "$(dirname "$INSTALL_DIR")" "$BIN_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  log "updating existing checkout at $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --depth=1 origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
elif [ -e "$INSTALL_DIR" ]; then
  printf 'lateral: install path exists but is not a git checkout: %s\n' "$INSTALL_DIR" >&2
  printf 'lateral: set LATERAL_INSTALL_DIR to another path or move that directory.\n' >&2
  exit 1
else
  log "cloning $REPO_URL into $INSTALL_DIR"
  git clone --depth=1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

log "using Python: $PYTHON_BIN"
log "creating Python environment at $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install -q --upgrade pip
"$VENV_DIR/bin/python" -m pip install -q "$INSTALL_DIR"

ln -sf "$VENV_DIR/bin/lateral" "$BIN_DIR/lateral"
log "installed CLI: $BIN_DIR/lateral"

if command -v claude >/dev/null 2>&1; then
  log "validating Claude Code plugin"
  claude plugin validate "$INSTALL_DIR/plugins/lateral-mode"
  claude plugin validate "$INSTALL_DIR"

  log "registering Claude Code marketplace"
  if ! claude plugin marketplace add "$INSTALL_DIR" --scope user; then
    log "marketplace add did not complete; it may already be configured"
  fi

  log "installing Claude Code plugin"
  if ! claude plugin install lateral-mode@lateral-local --scope user; then
    log "plugin install did not complete; it may already be installed"
  fi
else
  log "Claude Code was not found on PATH; CLI installed, plugin registration skipped"
fi

log "done"
log "if $BIN_DIR is not on PATH, add it to your shell profile"
log "try: lateral status --path ."
