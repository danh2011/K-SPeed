#!/usr/bin/env bash
# K-SPeed - bootstrap installer for macOS and Linux.
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh)"
#
# Fetches the repo into ~/.kspeed/repo, then launches the interactive manager.
# Extra flags are passed through, e.g.:  ... install.sh --yes --ksp "/path/to/KSP"
set -euo pipefail

REPO="${KSPEED_REPO:-OWNER/REPO}"
REF="${KSPEED_REF:-main}"
APP_HOME="${KSPEED_HOME:-$HOME/.kspeed}"
GIT_URL="${KSPEED_GIT_URL:-https://github.com/$REPO.git}"
SRC="$APP_HOME/repo"

say()  { printf "==> %s\n" "$*"; }
warn() { printf "!!  %s\n" "$*" >&2; }
die()  { warn "$*"; exit 1; }

if [ "$REPO" = "OWNER""/REPO" ] && [ -z "${KSPEED_GIT_URL:-}" ]; then
  die "This script still has the OWNER/REPO placeholder. Run tools/set_repo.py YOUR_USER/YOUR_REPO first."
fi

# ---- Python 3.8+ ------------------------------------------------------------
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  warn "Python 3.8 or newer is required."
  case "$(uname -s)" in
    Darwin) warn "Install it with:  brew install python   (or: xcode-select --install)";;
    *)      warn "Install it with your package manager, e.g.:  sudo apt install python3  |  sudo dnf install python3  |  sudo pacman -S python";;
  esac
  exit 1
fi

# ---- Fetch source -------------------------------------------------------------
mkdir -p "$APP_HOME"
if command -v git >/dev/null 2>&1; then
  if [ -d "$SRC/.git" ]; then
    say "Updating existing checkout"
    git -C "$SRC" fetch --quiet origin "$REF"
    git -C "$SRC" reset --hard --quiet FETCH_HEAD
  else
    say "Cloning $GIT_URL"
    rm -rf "$SRC"
    git clone --quiet --branch "$REF" "$GIT_URL" "$SRC"
  fi
else
  command -v curl >/dev/null 2>&1 || die "Need either git or curl."
  command -v tar  >/dev/null 2>&1 || die "Need tar."
  say "Downloading $REPO@$REF (git not found)"
  tmp="$(mktemp -d)"
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$REF" -o "$tmp/src.tgz"
  rm -rf "$SRC"; mkdir -p "$SRC"
  tar -xzf "$tmp/src.tgz" -C "$SRC" --strip-components=1
  rm -rf "$tmp"
fi

MANAGER="$SRC/installer/manager.py"
[ -f "$MANAGER" ] || die "Download looks wrong: $MANAGER not found."

# ---- Hand over to the manager ---------------------------------------------------
ARGS=(install --repo "$REPO" --ref "$REF")
# The script is usually piped from curl, so stdin is not a terminal. Reattach to /dev/tty for the TUI.
if ( : </dev/tty ) 2>/dev/null; then
  exec "$PY" "$MANAGER" "${ARGS[@]}" "$@" </dev/tty
else
  exec "$PY" "$MANAGER" "${ARGS[@]}" --yes "$@"
fi
