"""
ClawCapital — Main entry point
Loads .env, initialises the orchestrator and runs cycles.

Usage:
  python main.py                   # single cycle
  python main.py --loop 7200       # heartbeat every 2h (recommended)
  python main.py --loop 10800      # heartbeat every 3h
  python main.py --json            # print cycle output as JSON
  python main.py --skip-telegram   # auto-approve without Telegram (debug)
  python main.py --skip-heartbeat  # skip initial connectivity check (debug)
"""

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from orchestrator import Orchestrator
from executor.hyperliquid import HLMode


def build_orchestrator(skip_telegram: bool = False) -> Orchestrator:
    required = ["GEMINI_API_KEY"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"[ClawCapital] ERROR: missing variables in .env: {', '.join(missing)}")
        sys.exit(1)

    if not os.getenv("CRYPTOPANIC_TOKEN"):
        print("[ClawCapital] WARNING: CRYPTOPANIC_TOKEN not set — news pillar will be skipped")

    hl_mode_str = os.environ.get("HL_MODE", "paper").lower()
    hl_mode = {"paper": HLMode.PAPER, "test": HLMode.TEST, "live": HLMode.LIVE}.get(
        hl_mode_str, HLMode.PAPER
    )

    return Orchestrator(
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        cryptopanic_token=os.environ.get("CRYPTOPANIC_TOKEN"),
        coingecko_api_key=os.environ.get("COINGECKO_API_KEY"),
        alpha_vantage_key=os.environ.get("ALPHA_VANTAGE_API_KEY"),
        fred_api_key=os.environ.get("FRED_API_KEY"),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        hl_wallet_address=os.environ.get("HL_WALLET_ADDRESS"),
        hl_private_key=os.environ.get("HL_PRIVATE_KEY"),
        hl_agent_key=os.environ.get("HL_AGENT_KEY"),
        hl_mode=hl_mode,
        capital=float(os.environ.get("CAPITAL", "10000")),
        watchlist=os.environ.get("WATCHLIST", "BTC,ETH,SOL").split(","),
        max_risk_pct=float(os.environ.get("MAX_RISK_PCT", "1.0")),
        stop_loss_pct=float(os.environ.get("STOP_LOSS_PCT", "3.0")),
        risk_reward_ratio=float(os.environ.get("RISK_REWARD_RATIO", "2.0")),
        min_confidence=float(os.environ.get("MIN_CONFIDENCE", "0.60")),
        max_positions=int(os.environ.get("MAX_POSITIONS", "5")),
        max_av_tickers=int(os.environ.get("MAX_AV_TICKERS", "2")),
        telegram_timeout=int(os.environ.get("TELEGRAM_TIMEOUT", "300")),
        skip_telegram=skip_telegram,
    )


def run_once(orc: Orchestrator, skip_heartbeat: bool = False) -> dict:
    return orc.run_cycle(skip_heartbeat=skip_heartbeat)


def run_loop(orc: Orchestrator, interval_seconds: int, skip_heartbeat: bool = False) -> None:
    hours = interval_seconds / 3600
    print(f"[ClawCapital] Loop mode — heartbeat every {hours:.1f}h. Ctrl+C to stop.\n")

    running = True

    def _stop(sig, frame):
        nonlocal running
        print("\n[ClawCapital] Shutting down...")
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    cycle_count = 0
    while running:
        cycle_count += 1
        print(f"\n[ClawCapital] === CYCLE #{cycle_count} ===")
        try:
            output = run_once(orc, skip_heartbeat=skip_heartbeat)
            orders = output.get("executed_orders", [])
            print(f"[ClawCapital] Cycle #{cycle_count} complete | "
                  f"Orders: {len(orders)} | Status: {output.get('status')}")
        except Exception as e:
            print(f"[ClawCapital] Error in cycle #{cycle_count}: {e}")

        if running:
            next_run = time.strftime("%H:%M", time.localtime(time.time() + interval_seconds))
            print(f"[ClawCapital] Next cycle at {next_run} ({interval_seconds}s)...")
            time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(
        description="ClawCapital — Autonomous Quantitative Portfolio Manager"
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Interval between cycles in seconds (0 = single cycle; recommended: 7200 for 2h)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print cycle output as JSON",
    )
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="Auto-approve without Telegram (debug)",
    )
    parser.add_argument(
        "--skip-heartbeat",
        action="store_true",
        help="Skip connectivity heartbeat (debug)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  ClawCapital — Autonomous Quantitative Portfolio Manager")
    print("=" * 60)

    orc = build_orchestrator(skip_telegram=args.skip_telegram)

    if args.loop > 0:
        run_loop(orc, interval_seconds=args.loop, skip_heartbeat=args.skip_heartbeat)
    else:
        output = run_once(orc, skip_heartbeat=args.skip_heartbeat)
        if args.json:
            print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
