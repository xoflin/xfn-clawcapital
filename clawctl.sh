#!/usr/bin/env bash
# clawctl.sh — ClawCapital process manager
# Invocado pelo OpenClaw via skill ou directamente na shell
#
# Uso:
#   ./clawctl.sh start     → inicia loop de 2h em background
#   ./clawctl.sh stop      → para o processo
#   ./clawctl.sh restart   → stop + start
#   ./clawctl.sh status    → mostra se está a correr + últimas linhas de log
#   ./clawctl.sh once      → corre um ciclo único (debug)
#   ./clawctl.sh log       → tail do log em tempo real

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/clawcapital.pid"
LOG_FILE="$SCRIPT_DIR/logs/clawcapital.log"
PYTHON="$SCRIPT_DIR/venv/bin/python"
LOOP_INTERVAL="${LOOP_INTERVAL:-7200}"   # 2h default, override via env

mkdir -p "$SCRIPT_DIR/logs"

_is_running() {
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

cmd="${1:-status}"

case "$cmd" in
    start)
        if _is_running; then
            echo "⚠ ClawCapital already running (PID $(cat "$PID_FILE"))"
            exit 0
        fi
        echo "▶ Starting ClawCapital (loop=${LOOP_INTERVAL}s)..."
        nohup "$PYTHON" "$SCRIPT_DIR/main.py" \
            --loop "$LOOP_INTERVAL" \
            --skip-telegram \
            >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "✓ Started — PID $(cat "$PID_FILE")"
        echo "  Log: $LOG_FILE"
        ;;

    stop)
        if ! _is_running; then
            echo "⚠ ClawCapital is not running"
            rm -f "$PID_FILE"
            exit 0
        fi
        PID=$(cat "$PID_FILE")
        kill "$PID"
        rm -f "$PID_FILE"
        echo "■ Stopped (PID $PID)"
        ;;

    restart)
        "$0" stop || true
        sleep 2
        "$0" start
        ;;

    status)
        if _is_running; then
            PID=$(cat "$PID_FILE")
            UPTIME=$(ps -o etime= -p "$PID" 2>/dev/null | tr -d ' ' || echo "?")
            echo "● ClawCapital running  PID=$PID  uptime=$UPTIME"
            echo ""
            echo "── Last 10 lines ──────────────────────────────────"
            tail -10 "$LOG_FILE" 2>/dev/null || echo "(no log yet)"
        else
            echo "○ ClawCapital not running"
            rm -f "$PID_FILE"
        fi
        ;;

    once)
        echo "▶ Single cycle (no loop)..."
        "$PYTHON" "$SCRIPT_DIR/main.py" --skip-telegram --skip-heartbeat
        ;;

    log)
        echo "── Live log (Ctrl+C to exit) ──"
        tail -f "$LOG_FILE"
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|status|once|log}"
        exit 1
        ;;
esac
