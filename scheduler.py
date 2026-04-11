"""
Smart Scheduler — runs ClawCapital cycles at market-aligned intervals.

Instead of fixed loop intervals, this scheduler:
  1. Runs more frequently during peak market hours
  2. Runs less frequently (or skips) during dead hours
  3. Triggers learning analysis after each session

Market hours (UTC → PT summer UTC+1):
  Peak:    13:00-22:00 UTC (14:00-23:00 PT) — US session overlap
  Active:  07:00-13:00 UTC (08:00-14:00 PT) — European session
  Quiet:   22:00-07:00 UTC (23:00-08:00 PT) — Asian / off-hours

Usage:
  python scheduler.py                # runs indefinitely
  python scheduler.py --once         # picks next slot and runs once
"""

import time
import signal
import sys
from datetime import datetime, timezone

from main import build_orchestrator, run_once


# Schedule: (start_hour_utc, end_hour_utc, interval_minutes, label)
# Sorted by priority — checked in order, first match wins
SCHEDULE = [
    # US open + European overlap — highest volatility
    (13, 16, 60,  "US open"),
    # US session active
    (16, 21, 90,  "US session"),
    # US close — reversals common
    (21, 23, 60,  "US close"),
    # European session
    (7,  13, 120, "Europe"),
    # Asian session + overnight
    (23, 24, 240, "Asia night"),
    (0,  7,  240, "Asia night"),
]


def _current_slot() -> tuple:
    """Returns (interval_minutes, label) for current UTC hour."""
    hour = datetime.now(timezone.utc).hour
    for start, end, interval, label in SCHEDULE:
        if start <= hour < end:
            return interval, label
    return 240, "off-hours"  # fallback


def _next_run_str(seconds: int) -> str:
    """Human-readable next run time."""
    t = time.localtime(time.time() + seconds)
    return time.strftime("%H:%M", t)


def run_scheduled(skip_telegram: bool = True, once: bool = False):
    """Main scheduler loop."""
    orc = build_orchestrator(skip_telegram=skip_telegram)

    running = True
    def _stop(sig, frame):
        nonlocal running
        print("\n[Scheduler] Shutting down...")
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    cycle_count = 0
    while running:
        interval, label = _current_slot()
        cycle_count += 1

        print(f"\n[Scheduler] Cycle #{cycle_count} — {label} (interval: {interval}min)")

        try:
            run_once(orc, skip_heartbeat=(cycle_count > 1))
        except Exception as e:
            print(f"[Scheduler] Error: {e}")

        if once:
            break

        if running:
            wait_s = interval * 60
            print(f"[Scheduler] Next cycle at {_next_run_str(wait_s)} ({interval}min — {label})")
            # Sleep in small chunks to allow clean shutdown
            end_time = time.time() + wait_s
            while running and time.time() < end_time:
                time.sleep(min(30, end_time - time.time()))
                # Re-check slot — if we crossed into a new slot, adjust
                new_interval, new_label = _current_slot()
                if new_label != label:
                    new_wait = new_interval * 60
                    remaining = end_time - time.time()
                    if new_wait < remaining:
                        # Moved to higher-priority slot — wake up sooner
                        print(f"  [Scheduler] Slot changed → {new_label} ({new_interval}min)")
                        break


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ClawCapital Smart Scheduler")
    parser.add_argument("--once", action="store_true", help="Run single cycle then exit")
    parser.add_argument("--skip-telegram", action="store_true", default=True)
    args = parser.parse_args()

    run_scheduled(skip_telegram=args.skip_telegram, once=args.once)
