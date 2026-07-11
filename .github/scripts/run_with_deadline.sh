#!/usr/bin/env bash
set -u

if [ "$#" -lt 3 ]; then
  echo "::error::usage: run_with_deadline.sh <deadline-seconds> <kill-after-seconds> <command> [args...]" >&2
  exit 2
fi

deadline_seconds="$1"
kill_after_seconds="$2"
shift 2

if ! [[ "$deadline_seconds" =~ ^[0-9]+$ ]] || [ "$deadline_seconds" -le 0 ]; then
  echo "::error::deadline-seconds must be a positive integer, got '$deadline_seconds'" >&2
  exit 2
fi
if ! [[ "$kill_after_seconds" =~ ^[0-9]+$ ]]; then
  echo "::error::kill-after-seconds must be a non-negative integer, got '$kill_after_seconds'" >&2
  exit 2
fi

write_timeout_outputs() {
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
      echo "status=vpn_connect_timeout"
      echo "nba-probe-status=timeout"
      echo "nba-probe-diagnostic=NBA probes did not complete before the command deadline"
      echo "attempted-servers-json=[]"
      echo "failed-servers-json=[]"
    } >> "$GITHUB_OUTPUT"
  fi
}

if command -v setsid >/dev/null 2>&1; then
  setsid "$@" &
  child_pid=$!
  kill_target="-$child_pid"
else
  "$@" &
  child_pid=$!
  kill_target="$child_pid"
fi

timeout_marker="${RUNNER_TEMP:-/tmp}/run-with-deadline-${child_pid}.timeout"
rm -f "$timeout_marker"

(
  sleep "$deadline_seconds"
  if kill -0 "$child_pid" 2>/dev/null; then
    echo "::error::Command exceeded ${deadline_seconds}s deadline: $*" > "$timeout_marker"
    write_timeout_outputs
    kill -TERM "$kill_target" 2>/dev/null || kill -TERM "$child_pid" 2>/dev/null || true
    if [ "$kill_after_seconds" -gt 0 ]; then
      sleep "$kill_after_seconds"
    fi
    kill -KILL "$kill_target" 2>/dev/null || kill -KILL "$child_pid" 2>/dev/null || true
  fi
) >/dev/null 2>&1 &
watchdog_pid=$!

wait "$child_pid"
rc=$?
kill "$watchdog_pid" 2>/dev/null || true
if [ -f "$timeout_marker" ]; then
  cat "$timeout_marker" >&2
  rm -f "$timeout_marker"
  exit 1
fi
if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ] || [ "$rc" -eq 143 ]; then
  write_timeout_outputs
fi
exit "$rc"
