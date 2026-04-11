#!/usr/bin/env bash
# clawctl.sh — ClawCapital process manager
# Invocado pelo OpenClaw ou directamente na shell
#
# Uso:
#   ./clawctl.sh start      → smart scheduler (market-aware intervals)
#   ./clawctl.sh stop       → para o processo
#   ./clawctl.sh restart    → stop + start
#   ./clawctl.sh status     → mostra se está a correr + últimas linhas de log
#   ./clawctl.sh once       → corre um ciclo único
#   ./clawctl.sh learn      → analisa trades e mostra lessons
#   ./clawctl.sh log        → tail do log em tempo real
#   ./clawctl.sh report     → resumo completo (status + learning + performance)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/clawcapital.pid"
LOG_FILE="$SCRIPT_DIR/logs/clawcapital.log"
PYTHON="$SCRIPT_DIR/venv/bin/python"

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
        echo "▶ Starting ClawCapital (smart scheduler)..."
        cd "$SCRIPT_DIR"
        nohup "$PYTHON" "$SCRIPT_DIR/scheduler.py" \
            --skip-telegram \
            >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "✓ Started — PID $(cat "$PID_FILE")"
        echo "  Schedule: US open 1h │ US session 1.5h │ Europe 2h │ Night 4h"
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
        else
            echo "○ ClawCapital not running"
            rm -f "$PID_FILE"
        fi
        echo ""
        echo "── Last 15 lines ──────────────────────────────────"
        tail -15 "$LOG_FILE" 2>/dev/null || echo "(no log yet)"
        ;;

    once)
        echo "▶ Single cycle..."
        cd "$SCRIPT_DIR"
        "$PYTHON" "$SCRIPT_DIR/main.py" --skip-telegram --skip-heartbeat
        ;;

    learn)
        echo "▶ Analyzing trade history..."
        cd "$SCRIPT_DIR"
        "$PYTHON" -c "
from skills.learning.trade_analyzer import analyze
import json
report = analyze()
print(f'Trades: {report[\"total_trades\"]}')
print(f'Win rate: {report[\"win_rate\"]:.0%}')
print(f'Total PnL: \${report[\"total_pnl_usd\"]:+,.2f}')
print()
if report['patterns']:
    print('Patterns:')
    for p in report['patterns']:
        print(f'  - {p}')
print()
if report['prompt_context']:
    print('Context injected into prompts:')
    print(report['prompt_context'])
else:
    print('No closed trades yet — learning starts after first position closes.')
"
        ;;

    log)
        echo "── Live log (Ctrl+C to exit) ──"
        tail -f "$LOG_FILE"
        ;;

    report)
        "$0" status
        echo ""
        echo "── Learning ────────────────────────────────────────"
        "$0" learn
        echo ""
        echo "── Quota ───────────────────────────────────────────"
        cd "$SCRIPT_DIR"
        "$PYTHON" -c "
from risk.quota import QuotaTracker
qt = QuotaTracker()
s = qt.summary()
for svc, data in s['usage'].items():
    print(f'  {svc:<16} {data[\"used\"]}/{data[\"limit\"]}  (remaining: {data[\"remaining\"]})')
" 2>/dev/null || echo "  (quota file not found)"
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|status|once|learn|log|report}"
        exit 1
        ;;
esac
