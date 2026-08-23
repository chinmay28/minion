#!/usr/bin/env bash
#
# The one place Minion's version number is assembled.
#
# Scheme: vYEAR.MONTH.PATCH — a calendar version, where PATCH is the
# repository's commit count, so `v2026.8.42` is the 42nd commit on the 2026.8
# line. The month is not zero-padded; that keeps the string valid semver.
#
#   - YEAR/MONTH are source constants, read out of examples/minion.py so there
#     is exactly one declaration of them in the tree. Bump them there when a
#     release line opens; they are not taken from the clock, which would move
#     the version without a commit.
#   - PATCH comes from `git rev-list --count HEAD`, which only exists where
#     there is a checkout. The device runs from cron with a bare PATH, so
#     minion.py does not count for itself: quickstart.sh calls this file once at
#     install time and bakes the number into the runner as
#     MINION_VERSION_PATCH.
#
# The constants are PARSED rather than imported on purpose. minion.py imports
# PIL, requests and the Waveshare driver at module level, none of which load off
# a Raspberry Pi — importing it to ask its version would fail everywhere except
# the device.
#
# Usage:
#   scripts/version.sh            # print e.g. v2026.8.42
#   scripts/version.sh --patch    # print just the commit count (42)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." >/dev/null 2>&1 && pwd)"
MINION_PY="$ROOT/examples/minion.py"

[ -f "$MINION_PY" ] || { echo "version.sh: cannot find $MINION_PY" >&2; exit 1; }

# Read `YEAR`/`MONTH` out of the source that declares them. The pattern is
# anchored at both ends so it can only match the constant assignment itself,
# never a mention of the word in a comment.
read_const() {
  sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*([0-9]+)[[:space:]]*$/\1/p" "$MINION_PY" | head -n 1
}

YEAR="$(read_const YEAR)"
MONTH="$(read_const MONTH)"
[ -n "$YEAR" ] || { echo "version.sh: could not find YEAR in $MINION_PY" >&2; exit 1; }
[ -n "$MONTH" ] || { echo "version.sh: could not find MONTH in $MINION_PY" >&2; exit 1; }
if [ "$MONTH" -lt 1 ] || [ "$MONTH" -gt 12 ]; then
  echo "version.sh: MONTH = $MONTH in $MINION_PY; want a calendar month (1-12)" >&2
  exit 1
fi

# The commit count on HEAD, or 0 when it can't be known — no repo (a tarball, or
# a copy that skipped .git), no git, or a *shallow* clone.
#
# Shallow is the trap, and it's why this isn't a bare `rev-list`: a clone made
# with `--depth 1` answers `rev-list --count HEAD` with `1`, which is not an
# error and not obviously wrong — it just quietly logs a run calling itself
# `2026.8.1`. Refuse it. Patch 0 is the agreed "could not identify this build"
# marker, and a version ending in `.0` is visibly not a real one rather than a
# plausible lie.
#
# A cheap clone that still carries the whole commit graph is
# `--filter=blob:none`, which is what quickstart.sh uses.
commit_count() {
  if ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    printf '0'
    return
  fi
  if [ "$(git -C "$ROOT" rev-parse --is-shallow-repository 2>/dev/null || echo unknown)" = true ]; then
    echo "version.sh: shallow git clone — the commit count is not the real one," >&2
    echo "            reporting patch 0. Use --filter=blob:none, or fetch --unshallow." >&2
    printf '0'
    return
  fi
  # A failed probe (git older than 2.15) is not proof of shallowness — fall
  # through and let the count itself answer.
  git -C "$ROOT" rev-list --count HEAD 2>/dev/null || printf '0'
}

PATCH="$(commit_count)"

# Must stay byte-identical to VERSION in examples/minion.py. `--patch` stays
# bare: that one is what the installer exports as MINION_VERSION_PATCH, which is
# the number alone.
if [ "${1:-}" = --patch ]; then
  printf '%s\n' "$PATCH"
else
  printf 'v%s.%s.%s\n' "$YEAR" "$MONTH" "$PATCH"
fi
