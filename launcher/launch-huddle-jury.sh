#!/bin/bash
# huddle jury launcher: opens ONE new iTerm tab and starts a session in it.
# The command is chosen from a fixed list of constants. Nothing typed by the user
# ever reaches the shell or the AppleScript: an unknown mode is rejected.
#
# Usage: launch-huddle-jury.sh [--print] [lite|full|plain]
#   lite   starts:  claude "/huddle jury"        (the skill asks for the proposal)
#   full   starts:  claude "/huddle jury full"   (the skill asks for the proposal)
#   plain  starts:  claude                   (you type /huddle jury yourself)
#   --print shows the command and opens nothing (for testing)

set -u

PRINT=0
if [ "${1-}" = "--print" ]; then PRINT=1; shift; fi
if [ "$#" -gt 1 ]; then echo "too many arguments" >&2; exit 2; fi

MODE="${1-lite}"   # default only when NO argument is given; an empty string is rejected below
case "$MODE" in
  lite)  CMD='claude "/huddle jury"' ;;
  full)  CMD='claude "/huddle jury full"' ;;
  plain) CMD='claude' ;;
  *) echo "usage: launch-huddle-jury.sh [--print] [lite|full|plain]" >&2; exit 2 ;;
esac

if [ "$PRINT" -eq 1 ]; then printf '%s\n' "$CMD"; exit 0; fi

DIR="$(cd "$(dirname "$0")" && pwd)"
osascript "$DIR/huddle-tab.applescript" "$CMD"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "huddle launcher: osascript failed (exit $rc). Either macOS blocked automation of iTerm (allow it in System Settings > Privacy & Security > Automation) or the command was refused." >&2
  exit "$rc"
fi
