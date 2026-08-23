#!/usr/bin/env bash
#
# Minion — Raspberry Pi quick-start installer (Raspberry Pi OS / Debian).
#
# One command, run as root, installs Minion as an `@reboot` crontab entry:
#
#   curl -fsSL https://raw.githubusercontent.com/chinmay28/minion/master/scripts/quickstart.sh | sudo bash
#
# Minion is NOT a long-running server. It is an appliance: the PiSugar RTC
# powers the Pi on, one run of examples/minion.py paints the e-paper panel,
# schedules the next wake-up, and powers the Pi back off. The installer is
# shaped around that, which is why it differs from a typical service installer:
#
#   * The boot hook is cron's `@reboot`, not a systemd unit. cron starts late in
#     boot, which is exactly what this workload wants: PiSugar is already
#     listening, so the battery reads and — far more importantly — the RTC
#     wake-up alarm land. One run per boot, no retry: a failed run must NOT
#     loop, the panel simply keeps the image it already holds until the next
#     wake. Any systemd unit a previous version of this script installed is
#     REMOVED, so exactly one scheduler owns the boot.
#   * NOTHING IS RUN AT INSTALL TIME by default. Starting minion.py sets an RTC
#     alarm and (if the server's auto-shutdown flag is set) powers the machine
#     off. An installer that "verified" itself by running the app would shut
#     down the Pi you are typing on. Set MINION_RUN_NOW=1 to opt in.
#   * There is no database and no health endpoint. The only state is the config
#     file ($MINION_CONFIG). It is created once and NEVER overwritten, so your
#     API URL and log path survive every upgrade.
#   * Instead of a health check we run preflight checks — fonts, Python imports,
#     SPI device node, Home API reachability, PiSugar socket, sudo rule. Missing
#     hardware-side pieces WARN rather than fail: this same script is useful on
#     a plain Debian box for staging, where there is no panel to talk to.
#   * The deployed code is a checkout this script OWNS, at $PREFIX/src. Every run
#     fetches $MINION_REF into it, so the running commit is always known and
#     "re-run to upgrade" means something. A hand-maintained checkout in a home
#     directory is whatever state it was left in, which is why it is not used by
#     default — point MINION_SRC_DIR at one to override.
#   * The crontab entry is written between BEGIN/END markers and rewritten on
#     every run, so upgrading never stacks duplicates. Any OTHER line launching
#     minion (a hand-rolled `@reboot cd ~/minion && …`) is commented out, not
#     deleted, and the previous crontab is backed up to $PREFIX/backups first.
#   * Idempotent. Re-run any time to upgrade in place. If the new checkout fails
#     its compile/import check, it is ROLLED BACK to the previous commit. A
#     MINION_SRC_DIR tree is only fast-forwarded, never when dirty, never reset.
#
# Configure via environment variables (all optional):
#
#   MINION_REPO           git URL to clone      (default: https://github.com/chinmay28/minion.git)
#   MINION_REF            branch/tag/commit     (default: master)
#   MINION_USER           user whose crontab gets the @reboot entry, and who the
#                         run happens as        (default: the invoking sudo user, else 'minion')
#   MINION_SRC_DIR        deploy YOUR checkout  (default: unset — clone and manage $PREFIX/src)
#   MINION_PREFIX         install prefix        (default: /opt/minion; source -> $PREFIX/src,
#                                               venv -> $PREFIX/venv)
#   MINION_CONFIG         env file the run loads (default: /etc/minion.env)
#   MINION_API_BASE_URL   Home API base URL     (seeded into the config on FIRST install only)
#   MINION_LOG_FILE       log path              (default: <service user's home>/minion.log)
#   MINION_PISUGAR_WAIT   seconds to wait at boot for PiSugar to accept connections
#                                               (default: 30; 0 disables — seeded into the config)
#   ENABLE_SPI            auto | never          enable the SPI interface (default: auto)
#   MINION_RUN_NOW        0 | 1                 run one refresh after install — MAY POWER OFF THE PI
#                                               (default: 0)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'; C_YELLOW=$'\033[1;33m'
  C_RED=$'\033[1;31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_DIM=''; C_OFF=''
fi
log()  { printf '%s==>%s %s\n' "$C_BLUE" "$C_OFF" "$*"; }
ok()   { printf '%s ok %s %s\n' "$C_GREEN" "$C_OFF" "$*"; }
warn() { printf '%swarn%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; WARNINGS=$((WARNINGS + 1)); }
die()  { printf '%serr %s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }
step() { printf '\n%s%s%s\n' "$C_DIM" "$*" "$C_OFF"; }
WARNINGS=0

# ---------------------------------------------------------------------------
# Must be root (installs under /opt, edits another user's crontab, SPI config,
# sudoers rule, and removes any system unit an earlier version left behind)
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  die "Run as root: curl -fsSL .../quickstart.sh | sudo bash   (or: sudo ./scripts/quickstart.sh)"
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MINION_REPO="${MINION_REPO:-https://github.com/chinmay28/minion.git}"
MINION_REF="${MINION_REF:-master}"
PREFIX="${MINION_PREFIX:-/opt/minion}"
CONFIG_FILE="${MINION_CONFIG:-/etc/minion.env}"
ENABLE_SPI="${ENABLE_SPI:-auto}"
MINION_RUN_NOW="${MINION_RUN_NOW:-0}"

# The service user. Prefer whoever invoked sudo — on the original device Minion
# runs as a normal login user (its log lives in that user's home, and that user
# is already in the spi/gpio groups). Fall back to a dedicated system account
# when the script is piped in from a root shell with no SUDO_USER.
SVC_USER="${MINION_USER:-}"
if [ -z "$SVC_USER" ]; then
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ] && id -u "$SUDO_USER" >/dev/null 2>&1; then
    SVC_USER="$SUDO_USER"
  else
    SVC_USER="minion"
  fi
fi

SVC_HOME="$(getent passwd "$SVC_USER" 2>/dev/null | cut -d: -f6)"
[ -n "$SVC_HOME" ] || SVC_HOME="/var/lib/$SVC_USER"

VENV_DIR="$PREFIX/venv"
VENV_PY="$VENV_DIR/bin/python"
SERVICE_NAME="minion"
# Kept only so the systemd unit an earlier version of this script installed can
# be found and torn down; nothing here writes it any more.
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
SUDOERS_PATH="/etc/sudoers.d/minion"
RUNNER="$PREFIX/bin/minion-run"
WAIT_HELPER="$PREFIX/bin/wait-for-pisugar"
# Marker lines around the managed crontab block. ASCII only — a crontab is not
# the place to find out how the cron daemon feels about UTF-8. The block is
# matched on the "# BEGIN minion" prefix alone, so the rest of the text can be
# reworded later without orphaning the block on already-deployed devices.
CRON_BEGIN_PREFIX="# BEGIN minion"
CRON_BEGIN="$CRON_BEGIN_PREFIX - managed by quickstart.sh, rewritten on every run"
CRON_END="# END minion"

# Is this actually a Pi? The Waveshare driver picks its GPIO backend by grepping
# /proc/cpuinfo, so anything else is a staging install: set it up, warn, move on.
IS_PI=0
grep -qi raspberry /proc/cpuinfo 2>/dev/null && IS_PI=1

is_minion_tree() { [ -f "$1/examples/minion.py" ] && [ -d "$1/lib/waveshare_epd" ]; }

# Where the code lives. The default is a checkout this script owns at
# $PREFIX/src: every run fetches $MINION_REF into it, so "re-run to upgrade"
# actually means something and the deployed commit is always known. A checkout
# sitting in someone's home is not that — it is whatever state it was left in.
#
# MINION_SRC_DIR opts out and points the boot run at a tree you maintain yourself
# (a dev checkout, an air-gapped copy). ADOPTED=1 marks that case: we never
# chown it, reset it, or roll it back.
SRC_DIR="$PREFIX/src"
ADOPTED=0
if [ -n "${MINION_SRC_DIR:-}" ]; then
  is_minion_tree "$MINION_SRC_DIR" \
    || die "MINION_SRC_DIR=$MINION_SRC_DIR is not a Minion checkout (no examples/minion.py + lib/waveshare_epd)."
  SRC_DIR="$MINION_SRC_DIR"; ADOPTED=1
fi

log "Minion quick start"
printf '  %-10s %s\n' "source"  "$SRC_DIR"
printf '  %-10s %s\n' "venv"    "$VENV_DIR"
printf '  %-10s %s\n' "config"  "$CONFIG_FILE"
printf '  %-10s %s\n' "boot"    "@reboot crontab entry (user: $SVC_USER)"
[ "$ADOPTED" -eq 1 ] && printf '  %-12s %s\n' "" "(MINION_SRC_DIR — your tree; left as you keep it)"
[ "$IS_PI" -eq 1 ] || printf '  %-10s %s\n' "platform" "not a Raspberry Pi — display/PiSugar steps will be skipped"

# Run git/python as the service user so the tree stays owned by them (git
# refuses to read a repo owned by someone else) and so the checks see the same
# environment the boot run will. HOME is set explicitly: runuser keeps the caller's
# environment, and leaving HOME=/root makes git and pip read root's config.
as_svc() {
  if id -u "$SVC_USER" >/dev/null 2>&1; then
    if command -v runuser >/dev/null 2>&1; then
      runuser -u "$SVC_USER" -- env HOME="$SVC_HOME" "$@"
    else
      sudo -u "$SVC_USER" --preserve-env=PATH env HOME="$SVC_HOME" "$@"
    fi
  else
    "$@"
  fi
}

# Detect an upgrade BEFORE anything changes, so we know whether to roll back.
# A leftover unit file counts: a device installed by the systemd-era version of
# this script is an upgrade even though it has no crontab entry yet.
UPGRADE=0
{ [ -f "$UNIT_PATH" ] || [ -f "$CONFIG_FILE" ] || [ -x "$RUNNER" ]; } && UPGRADE=1

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
step "[1/8] Prerequisites"

APT=0; command -v apt-get >/dev/null 2>&1 && APT=1
APT_UPDATED=0
apt_refresh() {
  [ "$APT_UPDATED" -eq 1 ] && return 0
  apt-get update -y >/dev/null 2>&1 || true
  APT_UPDATED=1
}
# ensure_pkg <command> <apt-package>  — required; fail if it cannot be installed.
ensure_pkg() {
  command -v "$1" >/dev/null 2>&1 && return 0
  [ "$APT" -eq 1 ] || die "'$1' is missing and there is no apt-get to install it. Install it and re-run."
  log "installing ${2:-$1}…"
  apt_refresh
  apt-get install -y "${2:-$1}" >/dev/null 2>&1 || die "could not install ${2:-$1}."
}
# ensure_apt_optional <apt-package> — best effort; a failure only warns.
ensure_apt_optional() {
  [ "$APT" -eq 1 ] || return 0
  dpkg -s "$1" >/dev/null 2>&1 && return 0
  apt_refresh
  apt-get install -y "$1" >/dev/null 2>&1 || warn "could not install $1 (continuing)."
}

ensure_pkg git
ensure_pkg curl
ensure_pkg python3
# cron IS the scheduler now — without it nothing runs at boot at all.
ensure_pkg crontab cron
# The renderer's font, and netcat — minion.py talks to PiSugar by piping a line
# into `nc`, so without it the battery reading and the RTC alarm both fail.
ensure_apt_optional fonts-dejavu-core
ensure_apt_optional netcat-openbsd
# venv + the Pi GPIO stack from apt. On Raspberry Pi OS these are the packages
# that are actually built for the board; installing them first means pip finds
# them already satisfied inside a --system-site-packages venv instead of trying
# to compile spidev/lgpio from source.
ensure_apt_optional python3-venv
ensure_apt_optional python3-pip
ensure_apt_optional python3-pil
ensure_apt_optional python3-requests
if [ "$IS_PI" -eq 1 ]; then
  ensure_apt_optional python3-spidev
  ensure_apt_optional python3-gpiozero
  ensure_apt_optional python3-lgpio
fi
ok "git $(git --version | awk '{print $3}'), $(python3 --version), crontab present"
command -v nc >/dev/null 2>&1 || warn "netcat ('nc') not found — battery reads and RTC alarms will fail."

# ---------------------------------------------------------------------------
# 2. Service account
# ---------------------------------------------------------------------------
step "[2/8] Service account '$SVC_USER'"
if id -u "$SVC_USER" >/dev/null 2>&1; then
  ok "user '$SVC_USER' already exists"
else
  useradd --system --create-home --home-dir "$SVC_HOME" \
          --shell "$(command -v nologin || echo /usr/sbin/nologin)" "$SVC_USER"
  ok "created system user '$SVC_USER'"
fi
SVC_GROUP="$(id -gn "$SVC_USER")"

# SPI/GPIO access without root. These groups only exist on Raspberry Pi OS
# (its udev rules own the device nodes), so add only what is present.
for grp in spi gpio; do
  if getent group "$grp" >/dev/null 2>&1; then
    if id -nG "$SVC_USER" | tr ' ' '\n' | grep -qx "$grp"; then :; else
      usermod -aG "$grp" "$SVC_USER" && ok "added '$SVC_USER' to group '$grp'"
    fi
  fi
done

# minion.py ends a run with `sudo /sbin/shutdown -h now`. Grant exactly that.
if [ "$SVC_USER" = root ]; then
  ok "running as root — no sudoers rule needed"
elif command -v visudo >/dev/null 2>&1; then
  tmp_sudo="$(mktemp)"
  printf '%s ALL=(root) NOPASSWD: /sbin/shutdown\n' "$SVC_USER" > "$tmp_sudo"
  if visudo -cf "$tmp_sudo" >/dev/null 2>&1; then
    install -m 440 -o root -g root "$tmp_sudo" "$SUDOERS_PATH"
    ok "passwordless /sbin/shutdown granted ($SUDOERS_PATH)"
  else
    warn "generated sudoers rule failed validation — the Pi will not be able to power itself off."
  fi
  rm -f "$tmp_sudo"
else
  warn "visudo not found — skipping the shutdown sudoers rule; the Pi will not power itself off."
fi

# ---------------------------------------------------------------------------
# 3. Source
# ---------------------------------------------------------------------------
step "[3/8] Source at $SRC_DIR"
PREV_SHA=""
if [ "$ADOPTED" -eq 1 ]; then
  # This tree belongs to the user, not to us: never reset a branch under them.
  # Fast-forward only, and only when there is nothing to lose.
  PREV_SHA="$(as_svc git -C "$SRC_DIR" rev-parse HEAD 2>/dev/null || true)"
  log "using your own checkout (MINION_SRC_DIR) — not managed by this script"
  if [ ! -d "$SRC_DIR/.git" ]; then
    ok "source at $SRC_DIR (not a git checkout — left as is)"
  elif [ -n "$(as_svc git -C "$SRC_DIR" status --porcelain 2>/dev/null)" ]; then
    warn "$SRC_DIR has uncommitted changes — leaving it untouched."
  elif as_svc git -C "$SRC_DIR" pull --ff-only >/dev/null 2>&1; then
    ok "fast-forwarded to $(as_svc git -C "$SRC_DIR" rev-parse --short HEAD)"
  else
    warn "could not fast-forward $SRC_DIR (no upstream, or diverged) — leaving it as is."
  fi
elif [ -d "$SRC_DIR/.git" ]; then
  # Every git call here goes through as_svc. The tree is owned by $SVC_USER, and
  # git refuses to touch a repo owned by someone else ("dubious ownership") — as
  # root this returns nothing, PREV_SHA ends up empty, and the rollback below is
  # silently skipped exactly when it is needed.
  PREV_SHA="$(as_svc git -C "$SRC_DIR" rev-parse HEAD 2>/dev/null || true)"
  log "updating to $MINION_REF…"
  as_svc git -C "$SRC_DIR" fetch --prune origin "$MINION_REF" \
    || die "git fetch failed — check connectivity to $MINION_REPO"
  as_svc git -C "$SRC_DIR" checkout -q -B deploy FETCH_HEAD
  ok "updated $( [ -n "$PREV_SHA" ] && echo "${PREV_SHA:0:12} → " )$(as_svc git -C "$SRC_DIR" rev-parse --short HEAD)"
else
  log "cloning $MINION_REPO (ref: $MINION_REF)…"
  # Clone as the service user, like every other git call, so the tree is theirs
  # from the start. $PREFIX has to be handed over first — they cannot mkdir in
  # /opt. (Cloning as root and chowning afterwards also works over https, but
  # breaks for a local-path origin the service user owns.)
  mkdir -p "$PREFIX"
  chown "$SVC_USER":"$SVC_GROUP" "$PREFIX" 2>/dev/null || true
  # NOT --depth 1: the version's patch number is the commit count, and a shallow
  # clone would make every run log itself as 2026.8.1. --filter=blob:none keeps
  # it cheap — the whole commit graph, but only the blobs the checkout needs.
  # Fall back for git < 2.19, then for a ref that is not a branch.
  as_svc git clone --filter=blob:none --branch "$MINION_REF" "$MINION_REPO" "$SRC_DIR" \
    || as_svc git clone --branch "$MINION_REF" "$MINION_REPO" "$SRC_DIR" \
    || as_svc git clone "$MINION_REPO" "$SRC_DIR" \
    || die "clone failed — check connectivity to $MINION_REPO"
  ok "cloned to $SRC_DIR"
fi
# Only take ownership of trees we manage; a MINION_SRC_DIR checkout belongs to
# whoever maintains it and is none of our business.
[ "$ADOPTED" -eq 1 ] || chown -R "$SVC_USER":"$SVC_GROUP" "$PREFIX" 2>/dev/null || true
is_minion_tree "$SRC_DIR" || die "no examples/minion.py + lib/waveshare_epd at $SRC_DIR — checkout failed?"

# The service user has to be able to reach the code at boot. A checkout under a
# 0700 home is readable by its owner, but if the run ever happens as someone else
# this is the failure that shows up as a mysterious ExecStart=203/EXEC.
as_svc test -r "$SRC_DIR/examples/minion.py" \
  || warn "'$SVC_USER' cannot read $SRC_DIR/examples/minion.py — check the permissions on $SRC_DIR."

# The version is vYEAR.MONTH.<commit count> (scripts/version.sh). Count once,
# here, and bake the number into the runner below: the boot run happens from
# cron with a bare PATH on a battery device, so it must not shell out to git for
# a number that cannot change between reboots. A tree with no .git — or a
# shallow one, which version.sh refuses to guess around — leaves it at 0, and a
# run logging v2026.8.0 says so rather than claiming a release it isn't.
VERSION_PATCH="$(as_svc "$SRC_DIR/scripts/version.sh" --patch 2>/dev/null || echo 0)"
MINION_VERSION="$(as_svc "$SRC_DIR/scripts/version.sh" 2>/dev/null || echo "v?.?.0")"
if [ "$VERSION_PATCH" = 0 ]; then
  warn "could not count this checkout's commits — runs will log $MINION_VERSION."
else
  ok "version $MINION_VERSION"
fi

# ---------------------------------------------------------------------------
# 4. Python environment (+ the check that gates a rollback)
# ---------------------------------------------------------------------------
step "[4/8] Python environment"

# pip runs as root but the app runs as $SVC_USER. PYTHONNOUSERSITE stops pip
# from counting packages in root's ~/.local as "already satisfied" — those are
# unreadable to the service user, so the install would look fine and the app
# would still fail to import at boot.
pip_run() { env PYTHONNOUSERSITE=1 "$VENV_PY" -m pip "$@"; }

# --system-site-packages so the venv can see apt's spidev/gpiozero/lgpio, which
# are board-specific and should not be rebuilt from source by pip.
build_env() {
  if [ ! -x "$VENV_PY" ]; then
    log "creating venv at $VENV_DIR…"
    python3 -m venv --system-site-packages "$VENV_DIR" \
      || die "python3 -m venv failed — install python3-venv and re-run."
  fi
  pip_run install --quiet --upgrade pip >/dev/null 2>&1 || true
  log "installing Python dependencies…"
  if ! pip_run install --quiet -r "$SRC_DIR/requirements.txt" >"$BUILD_LOG" 2>&1; then
    # Expected off-Pi: spidev/gpiozero/lgpio have no wheels for a generic host.
    warn "full requirements.txt install failed (normal off a Pi) — installing Pillow + requests only."
    pip_run install --quiet Pillow requests >"$BUILD_LOG" 2>&1 \
      || { sed -n '$p' "$BUILD_LOG" >&2; die "could not install Pillow/requests into $VENV_DIR"; }
  fi
  chown -R "$SVC_USER":"$SVC_GROUP" "$VENV_DIR" 2>/dev/null || true
}

# The realistic off-device check (there is no test suite and the hardware cannot
# be exercised here): does the app compile, and can the service user import its
# pure-Python deps? Run as $SVC_USER, not root — "root can import it" is not the
# question. Compile to a temp file so no __pycache__ is left in the checkout.
verify_build() {
  local tmpd rc=0
  # py_compile writes atomically (write + rename), so the target directory must
  # belong to the user doing the compiling — a root-owned mktemp file would only
  # produce a confusing EPERM.
  tmpd="$(mktemp -d)"
  chown "$SVC_USER" "$tmpd"
  as_svc "$VENV_PY" -c \
    'import py_compile,sys; py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)' \
    "$SRC_DIR/examples/minion.py" "$tmpd/minion.pyc" >"$BUILD_LOG" 2>&1 || rc=1
  rm -rf "$tmpd"
  [ "$rc" -eq 0 ] || return 1
  as_svc "$VENV_PY" -c 'from PIL import Image, ImageDraw, ImageFont; import requests' \
    >"$BUILD_LOG" 2>&1 || return 1
  # Resolve the vendored driver exactly as the boot run will — same user, same
  # PYTHONPATH. find_spec stops at the parent packages (both __init__.py are
  # empty), so this proves the import path without importing epdconfig, which
  # would seize the GPIO pins the moment it loaded.
  as_svc env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$SRC_DIR" "$VENV_PY" -c \
    'import importlib.util as u, sys
sys.exit(0 if u.find_spec("lib.waveshare_epd.epd2in13_V4") else 1)' \
    >"$BUILD_LOG" 2>&1 || return 1
  return 0
}

BUILD_LOG="$(mktemp)"
trap 'rm -f "$BUILD_LOG"' EXIT

build_env
if ! verify_build; then
  # --system-site-packages means pip treats a distro Pillow/requests as already
  # satisfied — even when the distro copy is broken or built for another Python.
  # Shadow it with a venv-local copy and re-check before calling this a failure.
  warn "Pillow/requests are not usable as installed — reinstalling them inside the venv…"
  pip_run install --quiet --ignore-installed Pillow requests >"$BUILD_LOG" 2>&1 || true
  chown -R "$SVC_USER":"$SVC_GROUP" "$VENV_DIR" 2>/dev/null || true
fi

if verify_build; then
  ok "dependencies installed; examples/minion.py compiles"
else
  warn "the new checkout failed its compile/import check:"
  sed -n '1,20p' "$BUILD_LOG" >&2
  # Only roll back a tree we manage. Checking out a different commit in someone's
  # own checkout would be a rude surprise, so an adopted tree is left alone.
  if [ "$UPGRADE" -eq 1 ] && [ -n "$PREV_SHA" ] && [ "$ADOPTED" -eq 0 ]; then
    warn "rolling back to ${PREV_SHA:0:12}…"
    as_svc git -C "$SRC_DIR" checkout -q -B deploy "$PREV_SHA"
    build_env
    verify_build \
      && die "Upgrade failed its check — rolled back to ${PREV_SHA:0:12}. Your config at $CONFIG_FILE is untouched." \
      || die "Upgrade AND rollback both failed. Inspect: $SRC_DIR"
  fi
  die "examples/minion.py does not compile or Pillow/requests are missing. Inspect: $SRC_DIR"
fi

# ---------------------------------------------------------------------------
# 5. Configuration
# ---------------------------------------------------------------------------
step "[5/8] Configuration at $CONFIG_FILE"

# Written once, never rewritten. This file is the only state Minion has, and it
# is what makes one deployment differ from another — clobbering it on upgrade
# would silently repoint a device at the original owner's tailnet.
if [ -f "$CONFIG_FILE" ]; then
  ok "existing config preserved (edit by hand; the next boot picks it up)"
else
  api_url="${MINION_API_BASE_URL:-http://nakedpi.stingray-boga.ts.net:9999/api/entries}"
  log_file="${MINION_LOG_FILE:-$SVC_HOME/minion.log}"
  cat > "$CONFIG_FILE" <<CONF
# Minion configuration — loaded by $RUNNER, which the @reboot
# crontab entry runs. KEY=value only (no 'export', no shell expansion): the
# runner parses this file line by line rather than sourcing it, so a stray line
# cannot execute anything. Re-running quickstart.sh never overwrites this file.
# Edits take effect on the next boot — there is no long-running process to
# restart.

# Home API base URL — already includes the /api/entries path.
# https://github.com/chinmay28/HomeAPI
MINION_API_BASE_URL=$api_url

# Where the run log goes (DEBUG level; start here when debugging a run).
MINION_LOG_FILE=$log_file

# TrueType font used by the renderer (from the fonts-dejavu-core package).
MINION_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf

# PiSugar server — battery reads and the RTC wake-up alarm.
MINION_PISUGAR_HOST=127.0.0.1
MINION_PISUGAR_PORT=8423

# Seconds to wait at boot for PiSugar to start accepting connections before
# running. cron fires late enough that this is usually insurance, but if PiSugar
# is not up the battery reads N/A and — much worse — the RTC wake-up alarm is
# never set, so the Pi never comes back. 0 disables the wait.
MINION_PISUGAR_WAIT=30
CONF
  chmod 644 "$CONFIG_FILE"
  ok "config written (API: $api_url)"
  [ -n "${MINION_API_BASE_URL:-}" ] || \
    warn "MINION_API_BASE_URL was not set — defaulted to the original device's tailnet address. Edit $CONFIG_FILE."
fi

# Read the effective values back (the file may have been hand-edited). Parsed
# rather than sourced, so a stray line cannot execute anything.
cfg_get() {
  local v
  v="$(sed -n "s/^[[:space:]]*$1=//p" "$CONFIG_FILE" 2>/dev/null | tail -n1)"
  v="${v%\"}"; v="${v#\"}"
  if [ -n "$v" ]; then printf '%s' "$v"; else printf '%s' "$2"; fi
}
CFG_API="$(cfg_get MINION_API_BASE_URL "")"
CFG_LOG="$(cfg_get MINION_LOG_FILE "$SVC_HOME/minion.log")"
CFG_FONT="$(cfg_get MINION_FONT_PATH /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf)"
CFG_PS_HOST="$(cfg_get MINION_PISUGAR_HOST 127.0.0.1)"
CFG_PS_PORT="$(cfg_get MINION_PISUGAR_PORT 8423)"

# The log file is opened at import time — if it is not writable, the app dies
# before it draws anything. Create it up front, owned by the service user.
log_dir="$(dirname "$CFG_LOG")"
if install -d -o "$SVC_USER" -g "$SVC_GROUP" "$log_dir" 2>/dev/null; then
  touch "$CFG_LOG" 2>/dev/null && chown "$SVC_USER":"$SVC_GROUP" "$CFG_LOG" 2>/dev/null || true
  ok "log file ready at $CFG_LOG"
else
  warn "could not prepare the log directory $log_dir — minion.py will fail to start if it cannot write $CFG_LOG."
fi

# ---------------------------------------------------------------------------
# 6. SPI interface
# ---------------------------------------------------------------------------
step "[6/8] SPI interface"
NEED_REBOOT=0
if [ "$IS_PI" -ne 1 ]; then
  ok "not a Raspberry Pi — skipping SPI setup"
elif [ -e /dev/spidev0.0 ]; then
  ok "SPI already enabled (/dev/spidev0.0)"
elif [ "$ENABLE_SPI" = never ]; then
  warn "SPI is off and ENABLE_SPI=never — the display will not initialise."
else
  if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_spi 0 >/dev/null 2>&1 || true
  fi
  if [ ! -e /dev/spidev0.0 ]; then
    boot_cfg=/boot/firmware/config.txt
    [ -f "$boot_cfg" ] || boot_cfg=/boot/config.txt
    if [ -f "$boot_cfg" ]; then
      grep -qE '^\s*dtparam=spi=on' "$boot_cfg" || printf '\ndtparam=spi=on\n' >> "$boot_cfg"
      ok "enabled SPI in $boot_cfg"
    else
      warn "no config.txt found — enable SPI manually (raspi-config → Interface Options → SPI)."
    fi
    NEED_REBOOT=1
  else
    ok "SPI enabled"
  fi
fi

# ---------------------------------------------------------------------------
# 7. Boot entry: @reboot crontab
# ---------------------------------------------------------------------------
step "[7/8] Boot entry (@reboot crontab)"

# --- PiSugar readiness gate -------------------------------------------------
# cron starts late in boot, so PiSugar is normally listening by the time this
# runs — but "normally" is doing real work there, and the failure is expensive:
# if PiSugar is not up, the battery reads N/A and, far worse, `rtc_alarm_set`
# goes nowhere and the Pi never wakes up again. So the run begins with a short,
# bounded wait for the port to accept a connection.
#
# It lives in its own file rather than inline in the crontab line because a
# crontab is a single-line-per-job format with its own `%` escaping — a shell
# loop written there would be unreadable and easy to break. In a file, none of
# that applies, and MINION_PISUGAR_* still arrive from $CONFIG_FILE, so editing
# the config keeps the gate and the app in sync.
install -d -o "$SVC_USER" -g "$SVC_GROUP" -m 755 "$PREFIX/bin"
cat > "$WAIT_HELPER" <<HELPER
#!/bin/sh
# Generated by quickstart.sh. Waits for the PiSugar server to accept
# connections, then execs out. ALWAYS exits 0: if PiSugar never appears, minion
# still runs and renders, and the auto-shutdown flag stays unread so the Pi
# stays powered on — the same fail-safe posture as an unreachable Home API.
h="\${MINION_PISUGAR_HOST:-127.0.0.1}"
p="\${MINION_PISUGAR_PORT:-8423}"
w="\${MINION_PISUGAR_WAIT:-30}"
exec $VENV_PY - "\$h" "\$p" "\$w" <<'PY'
import socket, sys, time
host, port, wait = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
if wait <= 0:
    sys.exit(0)
deadline = time.monotonic() + wait
while time.monotonic() < deadline:
    try:
        socket.create_connection((host, port), 1).close()
        sys.exit(0)
    except OSError:
        time.sleep(0.5)
print(f"pisugar not listening on {host}:{port} after {wait:.0f}s - battery will "
      "read N/A and the RTC wake-up alarm will NOT be set", file=sys.stderr)
PY
HELPER
chmod 755 "$WAIT_HELPER"
chown "$SVC_USER":"$SVC_GROUP" "$WAIT_HELPER" 2>/dev/null || true
ok "readiness gate installed ($WAIT_HELPER)"

# --- The runner the crontab entry calls -------------------------------------
# cron gives a job almost nothing: no EnvironmentFile, a bare PATH, and no
# working directory beyond $HOME. Everything the run needs is therefore set up
# here, in one file, so the crontab line stays a single readable command.
#
# PYTHONPATH is the whole ballgame. minion.py does
# `from lib.waveshare_epd import epd2in13_V4`, and lib/ is not an installed
# package. `cd` alone does NOT make that import work: running
# `python examples/minion.py` puts examples/ on sys.path[0], not the cwd, so the
# import fails with ModuleNotFoundError: No module named 'lib'. The repo root has
# to be on PYTHONPATH — exactly what the hand-rolled crontab line did with
# `export PYTHONPATH=$(pwd)`.
#
# The config is PARSED, not sourced: KEY=value lines only, so a stray line in
# $CONFIG_FILE cannot execute anything.
cat > "$RUNNER" <<RUNNER_EOF
#!/bin/sh
# Generated by quickstart.sh — do not edit; re-run the installer instead.
# One refresh of the e-paper panel. Invoked by the '@reboot' crontab entry of
# $SVC_USER, and safe to run by hand (knowing that a run sets an RTC alarm and
# may power the machine off).
set -u

# cron's PATH is minimal; minion.py shells out to nc and /sbin/shutdown.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

# Config: KEY=value lines only, parsed rather than sourced.
if [ -r "$CONFIG_FILE" ]; then
  while IFS= read -r line || [ -n "\$line" ]; do
    case "\$line" in
      ''|'#'*) continue ;;
      [A-Za-z_]*=*) export "\$line" ;;
    esac
  done < "$CONFIG_FILE"
fi

# Wait for PiSugar, but never block the run on it (the gate always exits 0).
[ -x "$WAIT_HELPER" ] && "$WAIT_HELPER"

cd "$SRC_DIR" || exit 1
export PYTHONPATH=$SRC_DIR
# The build this runner was generated for. minion.py cannot count commits at
# boot (see scripts/version.sh), so the installer passes the number it counted.
# Re-running the installer after an update rewrites this line.
export MINION_VERSION_PATCH=$VERSION_PATCH
exec $VENV_PY $SRC_DIR/examples/minion.py
RUNNER_EOF
chmod 755 "$RUNNER"
chown "$SVC_USER":"$SVC_GROUP" "$RUNNER" 2>/dev/null || true
ok "boot runner installed ($RUNNER)"

# --- Remove the systemd unit ------------------------------------------------
# Earlier versions of this script installed ${SERVICE_NAME}.service. Left
# enabled it fires at boot alongside the crontab entry: two processes grabbing
# the same GPIO pins (the loser dies with GPIOPinInUse) and both racing to shut
# the Pi down. cron is the scheduler now, so the unit goes — completely, not
# just disabled, or the next `systemctl enable` by muscle memory brings it back.
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files --no-legend 2>/dev/null | awk '{print $1}' | grep -qx "${SERVICE_NAME}.service"; then
    systemctl disable --now "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
    ok "stopped and disabled ${SERVICE_NAME}.service"
  fi
  systemctl reset-failed "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi
UNIT_REMOVED=0
for stale in "$UNIT_PATH" \
             "/etc/systemd/system/multi-user.target.wants/${SERVICE_NAME}.service" \
             "/etc/systemd/system/${SERVICE_NAME}.service.d/override.conf"; do
  [ -e "$stale" ] || [ -L "$stale" ] || continue
  rm -f "$stale" && UNIT_REMOVED=1
done
rmdir "/etc/systemd/system/${SERVICE_NAME}.service.d" 2>/dev/null || true
if [ "$UNIT_REMOVED" -eq 1 ]; then
  command -v systemctl >/dev/null 2>&1 && systemctl daemon-reload >/dev/null 2>&1 || true
  ok "removed the systemd unit — cron is the only boot hook now"
else
  ok "no systemd unit to remove"
fi

# --- Install/refresh the @reboot crontab entry ------------------------------
# Rewritten between markers on every run, so upgrading never stacks duplicates.
# Any OTHER minion launcher (the hand-rolled `@reboot cd ~/minion && …` a
# by-hand setup leaves behind) is commented out rather than deleted: it would
# otherwise fire from its own checkout, at a different commit, fighting this one
# for the GPIO pins. The whole crontab is backed up first.
CRON_LINE="@reboot $RUNNER >> $CFG_LOG 2>&1"
CRON_OLD="$(crontab -l -u "$SVC_USER" 2>/dev/null || true)"

if [ -n "$CRON_OLD" ]; then
  backup_dir="$PREFIX/backups"
  install -d -m 755 "$backup_dir"
  backup_file="$backup_dir/crontab.$SVC_USER.$(date +%Y%m%d%H%M%S)"
  printf '%s\n' "$CRON_OLD" > "$backup_file"
  chmod 600 "$backup_file"
  ok "backed up the existing crontab to $backup_file"
fi

CRON_NEW=""
in_block=0
disabled=0
while IFS= read -r line; do
  # Drop our own previous block wholesale — it is regenerated below.
  case "$line" in
    "$CRON_BEGIN_PREFIX"*) in_block=1; continue ;;
  esac
  if [ "$in_block" -eq 1 ]; then
    [ "$line" = "$CRON_END" ] && in_block=0
    continue
  fi
  # Any other live line that launches minion: comment out, keep for reference.
  if printf '%s' "$line" | grep -qE '^[[:space:]]*[^#].*(minion\.py|minion-run)'; then
    warn "disabling a competing crontab entry (kept, commented out):"
    printf '       %s\n' "$line" >&2
    CRON_NEW="$CRON_NEW# disabled by minion quickstart.sh: $line"$'\n'
    disabled=1
    continue
  fi
  CRON_NEW="$CRON_NEW$line"$'\n'
done <<< "$CRON_OLD"

# Strip the blank line an empty crontab leaves behind, then append our block.
[ "$CRON_NEW" = $'\n' ] && CRON_NEW=""
CRON_NEW="$CRON_NEW$CRON_BEGIN"$'\n'
CRON_NEW="$CRON_NEW# One refresh of the e-paper panel per boot. The PiSugar RTC is the real"$'\n'
CRON_NEW="$CRON_NEW# scheduler: minion.py sets the next wake-up alarm and powers the Pi off."$'\n'
CRON_NEW="$CRON_NEW# Deployed source: $SRC_DIR"$'\n'
CRON_NEW="$CRON_NEW$CRON_LINE"$'\n'
CRON_NEW="$CRON_NEW$CRON_END"$'\n'

printf '%s' "$CRON_NEW" | crontab -u "$SVC_USER" - \
  || die "could not install the crontab entry for '$SVC_USER'."
ok "@reboot entry installed for '$SVC_USER'"
[ "$disabled" -eq 1 ] && warn "  the disabled line(s) above are commented out in the crontab — delete them when you are happy."

# cron only honours @reboot if the daemon is actually enabled at boot.
if command -v systemctl >/dev/null 2>&1; then
  cron_unit=""
  for candidate in cron.service crond.service cronie.service; do
    systemctl list-unit-files --no-legend 2>/dev/null | awk '{print $1}' | grep -qx "$candidate" && { cron_unit="$candidate"; break; }
  done
  if [ -n "$cron_unit" ]; then
    systemctl enable "$cron_unit" >/dev/null 2>&1 || true
    systemctl start "$cron_unit" >/dev/null 2>&1 || true
    if systemctl is-enabled "$cron_unit" >/dev/null 2>&1; then
      ok "$cron_unit is enabled at boot"
    else
      warn "$cron_unit is not enabled — @reboot will never fire. Enable it: systemctl enable --now $cron_unit"
    fi
  else
    warn "no cron unit found — make sure the cron daemon starts at boot, or @reboot never fires."
  fi
fi

# The checkout the old hand-rolled entry used is now superseded. Say so plainly —
# otherwise it sits there looking authoritative while nothing runs it.
if [ "$ADOPTED" -eq 0 ] && [ "$SVC_HOME/minion" != "$SRC_DIR" ] && is_minion_tree "$SVC_HOME/minion"; then
  warn "$SVC_HOME/minion is no longer used — the @reboot entry runs $SRC_DIR, which this script"
  warn "  keeps up to date. Keep it for local work, delete it, or pass MINION_SRC_DIR=$SVC_HOME/minion"
  warn "  to deploy it instead."
fi

# ---------------------------------------------------------------------------
# 8. Preflight checks
# ---------------------------------------------------------------------------
step "[8/8] Preflight checks"

# Is the @reboot entry actually there, and does it call the runner we just
# wrote? Read it back out of the installed crontab — the artifact on disk is
# what boots, so that is what should be tested.
installed_cron="$(crontab -l -u "$SVC_USER" 2>/dev/null | grep -E "^@reboot .*$RUNNER" || true)"
if [ -n "$installed_cron" ]; then
  ok "@reboot entry present in '$SVC_USER' crontab"
  printf '       %s\n' "$installed_cron"
else
  warn "no @reboot entry calling $RUNNER in '$SVC_USER' crontab — nothing will run at boot."
fi

# Can the runner resolve the vendored driver? Same idea: parse the values out of
# the generated script rather than reusing this script's variables.
#
# `python <script>` sets sys.path[0] to the SCRIPT's directory (examples/), not
# the working directory, so a launcher that only cd's dies with "No module named
# 'lib'". Assigning sys.path[0] here reproduces that exactly without needing to
# write a probe file into the checkout. env -i is the point of the test: cron
# hands the job a bare environment, so nothing may depend on the caller's.
run_exec="$(sed -n 's/^exec //p' "$RUNNER")"
run_py="${run_exec%% *}"; run_script="${run_exec#* }"
run_pp="$(sed -n 's/^export PYTHONPATH=//p' "$RUNNER")"
run_wd="$(sed -n 's/^cd "\(.*\)" || exit 1$/\1/p' "$RUNNER")"
if ( cd "$run_wd" && as_svc env -i HOME="$SVC_HOME" PATH=/usr/bin:/bin \
     PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$run_pp" "$run_py" -c \
     'import sys, os, importlib.util as u
sys.path[0] = os.path.dirname(os.path.abspath(sys.argv[1]))
sys.exit(0 if u.find_spec("lib.waveshare_epd.epd2in13_V4") else 1)' \
     "$run_script" >/dev/null 2>&1 ); then
  ok "the boot runner resolves lib.waveshare_epd in a bare cron environment (PYTHONPATH=$run_pp)"
else
  warn "the boot runner CANNOT import lib.waveshare_epd — it will die with \"No module named 'lib'\"."
  warn "  the repo root must be on PYTHONPATH; cd'ing into it is not enough."
fi

# The config is read by the runner's KEY=value parser, not by a shell. A
# hand-edited file that picked up `export ` or `$(…)` still looks fine but
# silently leaves the run on minion.py's built-in defaults — which point at the
# original device. Cheap to check, so check.
bad_cfg="$(grep -nE '^[[:space:]]*(export[[:space:]]|[A-Za-z_][A-Za-z0-9_]*=.*[`$])' "$CONFIG_FILE" 2>/dev/null || true)"
if [ -n "$bad_cfg" ]; then
  warn "$CONFIG_FILE has line(s) the boot runner will not apply (plain KEY=value only —"
  warn "  no 'export', no shell expansion):"
  printf '%s\n' "$bad_cfg" | sed 's/^/       /' >&2
else
  ok "$CONFIG_FILE is plain KEY=value (readable by the boot runner)"
fi

# Font — Pillow must be able to load it, or the app dies at import time.
if as_svc "$VENV_PY" -c \
  'import sys; from PIL import ImageFont; ImageFont.truetype(sys.argv[1], 12)' "$CFG_FONT" >/dev/null 2>&1; then
  ok "font loads ($CFG_FONT)"
else
  warn "Pillow cannot load $CFG_FONT — install fonts-dejavu-core or fix MINION_FONT_PATH in $CONFIG_FILE."
fi

# GPIO stack — importing the modules is safe; instantiating the driver is not
# (epdconfig grabs the GPIO pins the moment it is imported), so stop at imports.
if [ "$IS_PI" -eq 1 ]; then
  if as_svc env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$SRC_DIR" "$VENV_PY" -c 'import spidev, gpiozero' >/dev/null 2>&1; then
    ok "spidev + gpiozero import"
  else
    warn "spidev/gpiozero do not import — the display will fail to initialise."
  fi
  if [ -e /dev/spidev0.0 ]; then
    as_svc test -r /dev/spidev0.0 \
      && ok "/dev/spidev0.0 readable by '$SVC_USER'" \
      || warn "/dev/spidev0.0 is not accessible to '$SVC_USER' — a reboot usually applies the new group membership."
  else
    warn "/dev/spidev0.0 does not exist yet — reboot to apply the SPI change."
  fi
fi

# Home API — unreachable is survivable by design (the run skips the display
# update and, critically, does NOT power the Pi off), so this only warns.
if [ -n "$CFG_API" ]; then
  if curl -fsS --max-time 6 "$CFG_API/minion-quotes" >/dev/null 2>&1; then
    ok "Home API reachable ($CFG_API)"
  else
    warn "cannot reach $CFG_API/minion-quotes — Minion will skip the display update and stay powered on."
  fi
fi

# PiSugar — no battery reading and, more importantly, no RTC alarm without it.
if [ "$IS_PI" -eq 1 ]; then
  if command -v nc >/dev/null 2>&1 &&
     printf 'get battery\n' | nc -q 0 -w 2 "$CFG_PS_HOST" "$CFG_PS_PORT" 2>/dev/null | grep -q battery; then
    ok "PiSugar responding on $CFG_PS_HOST:$CFG_PS_PORT"
  else
    warn "no PiSugar server on $CFG_PS_HOST:$CFG_PS_PORT — battery shows N/A and no wake-up alarm is scheduled."
    warn "  install it from https://github.com/PiSugar/pisugar-power-manager-rs, then re-run this script."
  fi

  # The gate must be runnable by the service user, or ExecStartPre is dead
  # weight. A 1-second budget proves it executes and exits 0 either way.
  if as_svc env MINION_PISUGAR_WAIT=1 MINION_PISUGAR_HOST="$CFG_PS_HOST" \
       MINION_PISUGAR_PORT="$CFG_PS_PORT" "$WAIT_HELPER" >/dev/null 2>&1; then
    ok "readiness gate runs as '$SVC_USER' (waits up to $(cfg_get MINION_PISUGAR_WAIT 30)s at boot)"
  else
    warn "$WAIT_HELPER did not run cleanly as '$SVC_USER' — the boot race is not covered."
  fi
fi

# The shutdown rule — without it the Pi never powers off and the battery drains.
if [ "$SVC_USER" != root ] && command -v sudo >/dev/null 2>&1; then
  sudo -n -l -U "$SVC_USER" /sbin/shutdown >/dev/null 2>&1 \
    && ok "'$SVC_USER' may run /sbin/shutdown without a password" \
    || warn "'$SVC_USER' cannot run /sbin/shutdown without a password — the Pi will stay on after each run."
fi

# ---------------------------------------------------------------------------
# Optional: one refresh now (opt-in — this can power the machine off)
# ---------------------------------------------------------------------------
if [ "$MINION_RUN_NOW" = 1 ]; then
  step "Running one refresh now (MINION_RUN_NOW=1)"
  warn "this schedules an RTC alarm and MAY SHUT THIS MACHINE DOWN (if minion-auto-shutdown is truthy)."
  # Exactly what cron will run at the next boot, in the same bare environment.
  as_svc env -i HOME="$SVC_HOME" PATH=/usr/bin:/bin "$RUNNER" \
    || warn "the run failed — see: tail -n 50 $CFG_LOG"
  ok "run finished (log: $CFG_LOG)"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
verb="installed"; [ "$UPGRADE" -eq 1 ] && verb="upgraded"
reboot_note=""
[ "$NEED_REBOOT" -eq 1 ] && reboot_note="
  ${C_YELLOW}Reboot required${C_OFF} — SPI was just enabled. \`sudo reboot\` and Minion runs on the way back up."

cat <<DONE

${C_GREEN}Minion $verb.${C_OFF} ${WARNINGS} warning(s) above.

  Version:  $MINION_VERSION
  Source:   $SRC_DIR
  Config:   $CONFIG_FILE
  Log:      $CFG_LOG
  Boot:     @reboot in '$SVC_USER' crontab -> $RUNNER (one refresh per boot)
  Upgrade:  re-run this script; your config is preserved and a bad commit rolls back.
$reboot_note
  Nothing has been run yet. Minion refreshes the panel on the NEXT boot, and the
  PiSugar RTC is what powers the Pi back on. To paint it now — knowing this sets
  an RTC alarm and may power the machine off:

    sudo -u $SVC_USER $RUNNER     # or re-run with MINION_RUN_NOW=1

  Inspect a run:
    tail -f $CFG_LOG
    crontab -l -u $SVC_USER          # the boot entry, between its BEGIN/END markers
${C_DIM}
  Not the device you meant to set up? \`sudo crontab -u $SVC_USER -e\` and delete the
  block between the minion markers — otherwise this machine will run Minion at
  every boot and power itself off afterwards.${C_OFF}
DONE
