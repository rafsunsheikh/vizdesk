#!/bin/sh
# vizdesk installer for Linux and macOS.
#
#   curl -sSL https://raw.githubusercontent.com/rafsunsheikh/vizdesk/main/packaging/install/install.sh | sh
#
# It installs vizdesk into its own environment and puts the `vizdesk` command on
# your PATH. Nothing else on your machine is touched: no system packages, no
# changes to the Python you already have.
#
# It prefers uv, then pipx, and falls back to a private virtual environment.
# All three give the same result. A plain `pip install` is deliberately not used,
# because on most current systems that fails with "externally-managed-environment".
#
# POSIX sh on purpose, so it runs under dash, ash and busybox as well as bash.
set -eu

BLUE=''; GREEN=''; YELLOW=''; RED=''; OFF=''
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BLUE=$(printf '\033[34m'); GREEN=$(printf '\033[32m')
  YELLOW=$(printf '\033[33m'); RED=$(printf '\033[31m'); OFF=$(printf '\033[0m')
fi
say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$BLUE" "$OFF" "$*"; }
ok()   { printf '%s  ok%s %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '%s warn%s %s\n' "$YELLOW" "$OFF" "$*" >&2; }
die()  { printf '%serror%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

VENV_HOME="${VIZDESK_HOME:-$HOME/.local/share/vizdesk}"
BIN_DIR="${VIZDESK_BIN:-$HOME/.local/bin}"
MIN_PY_MINOR=10

case "$(uname -s)" in
  Linux|Darwin) : ;;
  *) die "this installer supports Linux and macOS. On Windows use: pipx install vizdesk" ;;
esac

# A Python new enough to run vizdesk. Checked rather than assumed, because the
# failure otherwise happens deep inside pip with a confusing message.
find_python() {
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    have "$c" || continue
    if "$c" - <<PYEOF >/dev/null 2>&1
import sys; sys.exit(0 if sys.version_info[:2] >= (3, $MIN_PY_MINOR) else 1)
PYEOF
    then command -v "$c"; return 0; fi
  done
  return 1
}

step "Looking for a way to install"

# 1. uv, the fastest and the one that needs no Python of its own.
if have uv; then
  ok "using uv"
  uv tool install --force vizdesk
  METHOD="uv tool"

# 2. pipx, which does the same job and is common on Linux.
elif have pipx; then
  ok "using pipx"
  pipx install --force vizdesk
  METHOD="pipx"

# 3. Offer to fetch uv, since it is one small static binary and needs no Python.
elif have curl || have wget; then
  say "Neither uv nor pipx is installed."
  say "uv is a single small program that installs command-line tools cleanly."
  printf 'Install uv now? [Y/n] '
  # Read from the terminal, not from the pipe this script may be running through.
  if [ -r /dev/tty ]; then read -r reply < /dev/tty || reply=""; else reply=""; fi
  case "${reply:-Y}" in
    [Nn]*) reply=no ;;
    *)     reply=yes ;;
  esac

  if [ "$reply" = yes ]; then
    step "Installing uv"
    if have curl; then curl -LsSf https://astral.sh/uv/install.sh | sh
    else wget -qO- https://astral.sh/uv/install.sh | sh; fi
    # uv lands in ~/.local/bin or ~/.cargo/bin depending on version.
    for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
      [ -x "$d/uv" ] && PATH="$d:$PATH" && export PATH
    done
    have uv || die "uv was installed but is not on PATH. Open a new shell and run this script again."
    ok "uv installed"
    uv tool install --force vizdesk
    METHOD="uv tool"
  else
    reply=skip
  fi
fi

# 4. Last resort: a private virtual environment plus a small launcher. This
#    always works wherever a recent Python exists, and leaves the system alone.
if [ -z "${METHOD:-}" ]; then
  step "Falling back to a private virtual environment"
  PY=$(find_python) || die "Python 3.$MIN_PY_MINOR or newer is required, and none was found.
  Install Python, or install uv from https://astral.sh/uv, then run this again."
  ok "using $PY"
  rm -rf "$VENV_HOME"
  mkdir -p "$VENV_HOME" "$BIN_DIR"
  "$PY" -m venv "$VENV_HOME/env" || die "could not create a virtual environment with $PY"
  "$VENV_HOME/env/bin/python" -m pip install --quiet --upgrade pip
  "$VENV_HOME/env/bin/python" -m pip install --quiet vizdesk || die "pip could not install vizdesk"
  cat > "$BIN_DIR/vizdesk" <<LAUNCH
#!/bin/sh
exec "$VENV_HOME/env/bin/vizdesk" "\$@"
LAUNCH
  chmod +x "$BIN_DIR/vizdesk"
  METHOD="a private environment in $VENV_HOME"
fi

# Confirm it actually runs, rather than claiming success and leaving the user
# to find out otherwise.
step "Checking the install"
if have vizdesk; then
  VERSION=$(vizdesk --version 2>/dev/null || echo "installed")
  ok "$VERSION, via $METHOD"
  say ""
  say "Try it:    vizdesk your-data.csv"
  say "Or:        vizdesk            # opens the app, load a file from the Data tab"
elif [ -x "$BIN_DIR/vizdesk" ]; then
  ok "installed to $BIN_DIR/vizdesk, via $METHOD"
  warn "$BIN_DIR is not on your PATH. Add this to your shell profile:"
  say ""
  say "    export PATH=\"$BIN_DIR:\$PATH\""
  say ""
  say "Then open a new shell and run: vizdesk"
else
  die "vizdesk was installed but the command cannot be found. Please open an issue."
fi
