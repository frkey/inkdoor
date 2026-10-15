#!/bin/sh
# Name: inkdoor - start display
# Author: inkdoor
# DontUseFBInk
. /mnt/us/inkdoor/common.sh
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0  # already running
fi
if command -v setsid >/dev/null 2>&1; then
  setsid nohup /bin/sh "$DIR/loop.sh" >/dev/null 2>&1 < /dev/null &
else
  nohup /bin/sh "$DIR/loop.sh" >/dev/null 2>&1 < /dev/null &
fi
