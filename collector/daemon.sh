#!/usr/bin/env bash
# Goal Lit 수집기 로컬 작업기(127.0.0.1:8795) 및 주기적 자동 수집 데몬 관리 스크립트
set -euo pipefail

COLLECTOR_DIR="/workspace/lit-hub/collector"
LOG_DIR="$COLLECTOR_DIR/logs"
PID_WORKER="$LOG_DIR/local_worker.pid"
PID_LOOP="$LOG_DIR/auto_loop.pid"

mkdir -p "$LOG_DIR"

start_daemon() {
  if [ -f "$PID_WORKER" ] && kill -0 "$(cat "$PID_WORKER")" 2>/dev/null; then
    echo "local_worker already running (PID $(cat "$PID_WORKER"))"
  else
    nohup python3 "$COLLECTOR_DIR/local_worker.py" --host 127.0.0.1 --port 8795 \
      >> "$LOG_DIR/local_worker.log" 2>&1 &
    echo $! > "$PID_WORKER"
    echo "Started local_worker on 127.0.0.1:8795 (PID $(cat "$PID_WORKER"))"
  fi

  if [ -f "$PID_LOOP" ] && kill -0 "$(cat "$PID_LOOP")" 2>/dev/null; then
    echo "auto_collector loop already running (PID $(cat "$PID_LOOP"))"
  else
    nohup bash -c '
      while true; do
        python3 /workspace/lit-hub/collector/report_status.py --json > /workspace/lit-hub/collector/logs/latest_status.json 2>> /workspace/lit-hub/collector/logs/auto_loop.log || true
        sleep 300
      done
    ' >> "$LOG_DIR/auto_loop.log" 2>&1 &
    echo $! > "$PID_LOOP"
    echo "Started auto_collector status/queue loop (PID $(cat "$PID_LOOP"))"
  fi
}

stop_daemon() {
  for pf in "$PID_WORKER" "$PID_LOOP"; do
    if [ -f "$pf" ]; then
      pid="$(cat "$pf")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" || true
      fi
      rm -f "$pf"
    fi
  done
  echo "Stopped Goal Lit collector daemons."
}

status_daemon() {
  for name_pf in "local_worker:$PID_WORKER" "auto_loop:$PID_LOOP"; do
    name="${name_pf%%:*}"
    pf="${name_pf#*:}"
    if [ -f "$pf" ] && kill -0 "$(cat "$pf")" 2>/dev/null; then
      echo "$name: RUNNING (PID $(cat "$pf"))"
    else
      echo "$name: STOPPED"
    fi
  done
}

case "${1:-start}" in
  start) start_daemon ;;
  stop) stop_daemon ;;
  restart) stop_daemon; start_daemon ;;
  status) status_daemon ;;
  *) echo "Usage: $0 {start|stop|restart|status}"; exit 1 ;;
esac
