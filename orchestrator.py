"""
ClaWClawCapital Orchestrator
Pipeline: Investigator → Manager → Telegram → Hyperliquid

Cadence: heartbeat every 2-3h (configured via main.py --loop).
No order is executed without human approval via Telegram.
"""

import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from agents.investigator import InvestigatorAgent
from agents.manager import ManagerAgent
from executor.hyperliquid import HyperliquidExecutor, HLMode
from notifications.telegram import request_approval, send_notification, ApprovalResult
from skills.data_fetchers.coingecko import CoinGeckoClient


MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)


# ------------------------------------------------------------------
# Memory logger
# ------------------------------------------------------------------

def _append_to_log(filename: str, entry: dict) -> None:
    path = MEMORY_DIR / filename
    history: list = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    history.append(entry)
    if len(history) > 500:
        history = history[-500:]
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------

class Orchestrator:
    """
    Coordinates the investigator and manager agents, collects human approval
    via Telegram, and submits orders to Hyperliquid.

    Args:
        gemini_api_key:      Gemini key (Flash for investigator, Pro for manager).
        cryptopanic_token:   CryptoPanic token.
        coingecko_api_key:   CoinGecko key (optional).
        alpha_vantage_key:   Alpha Vantage key (25 req/day).
        fred_api_key:        FRED API key.
        telegram_bot_token:  Telegram bot token.
        telegram_chat_id:    User chat ID.
        hl_wallet_address:   Ethereum wallet address for Hyperliquid.
        hl_private_key:      Hyperliquid private key.
        hl_agent_key:        Hyperliquid agent key (optional).
        hl_mode:             PAPER | TEST | LIVE.
        capital:             Total capital in USD.
        watchlist:           List of tickers to monitor.
        max_risk_pct:        Maximum risk per trade (% of capital).
        stop_loss_pct:       Default stop loss (%).
        risk_reward_ratio:   Minimum risk/reward ratio.
        min_confidence:      Minimum confidence to generate a signal.
        max_positions:       Maximum open positions.
        max_av_tickers:      Tickers with Alpha Vantage analysis per cycle.
        telegram_timeout:    Seconds for the user to approve/reject.
        skip_telegram:       If True, auto-approves (debug/test mode).
    """

    def __init__(
        self,
        gemini_api_key: str,
        cryptopanic_token: str,
        coingecko_api_key: str | None = None,
        alpha_vantage_key: str | None = None,
        fred_api_key: str | None = None,
        telegram_bot_token: str | None = None,
        telegram_chat_id: str | None = None,
        hl_wallet_address: str | None = None,
        hl_private_key: str | None = None,
        hl_agent_key: str | None = None,
        hl_mode: HLMode = HLMode.PAPER,
        capital: float = 10_000.0,
        watchlist: list[str] | None = None,
        max_risk_pct: float = 1.0,
        stop_loss_pct: float = 3.0,
        risk_reward_ratio: float = 2.0,
        min_confidence: float = 0.60,
        max_positions: int = 5,
        max_av_tickers: int = 2,
        telegram_timeout: int = 300,
        skip_telegram: bool = False,
    ):
        self.capital       = capital
        self.watchlist     = [t.upper() for t in (watchlist or ["BTC", "ETH", "SOL"])]
        self.telegram_timeout = telegram_timeout
        self.skip_telegram    = skip_telegram

        self.investigator = InvestigatorAgent(
            gemini_api_key=gemini_api_key,
            cryptopanic_token=cryptopanic_token,
            coingecko_api_key=coingecko_api_key,
            alpha_vantage_key=alpha_vantage_key,
            fred_api_key=fred_api_key,
            max_av_tickers=max_av_tickers,
        )

        self.manager = ManagerAgent(
            gemini_api_key=gemini_api_key,
            capital=capital,
            max_risk_pct=max_risk_pct,
            stop_loss_pct=stop_loss_pct,
            risk_reward_ratio=risk_reward_ratio,
            min_confidence=min_confidence,
            max_positions=max_positions,
        )

        self.executor = HyperliquidExecutor(
            mode=hl_mode,
            wallet_address=hl_wallet_address,
            private_key=hl_private_key,
            agent_key=hl_agent_key,
        )

        self._tg_token   = telegram_bot_token
        self._tg_chat_id = telegram_chat_id
        self._coingecko  = CoinGeckoClient(api_key=coingecko_api_key)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _heartbeat(self) -> dict:
        """Checks essential modules before consuming API quotas."""
        checks: dict[str, bool] = {}

        try:
            self._coingecko.get("/ping", {})
            checks["coingecko"] = True
        except Exception:
            checks["coingecko"] = False

        try:
            import google.generativeai  # noqa: F401
            checks["gemini"] = True
        except Exception:
            checks["gemini"] = False

        checks["executor"] = True  # always OK in paper mode

        healthy = all(checks.values())
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "healthy":   healthy,
            "checks":    checks,
        }
        _append_to_log("heartbeat-log.json", result)
        return result

    # ------------------------------------------------------------------
    # Current prices (CoinGecko batch — 1 req)
    # ------------------------------------------------------------------

    def _get_current_prices(self) -> dict[str, float]:
        """Returns {TICKER: usd_price} for all watchlist tickers."""
        try:
            snapshots = self._coingecko.get_batch_snapshots(self.watchlist)
            return {s["ticker"]: s["price"] for s in snapshots if "price" in s}
        except Exception as e:
            print(f"[Orchestrator] WARNING — prices unavailable: {e}")
            return {}

    # ------------------------------------------------------------------
    # Telegram approval per decision
    # ------------------------------------------------------------------

    def _request_human_approval(self, decision: dict) -> ApprovalResult:
        """
        Sends thesis to user and waits for approval.
        If skip_telegram=True, auto-approves (debug mode).
        """
        if self.skip_telegram:
            print("  [Telegram] skip_telegram=True — auto-approved")
            return ApprovalResult(
                approved=True,
                decision="yes",
                responded_at=datetime.now(timezone.utc).isoformat(),
                reason="auto-approved (skip_telegram=True)",
            )

        if not self._tg_token or not self._tg_chat_id:
            print("  [Telegram] Missing credentials — rejecting for safety")
            return ApprovalResult(
                approved=False,
                decision="error",
                reason="TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured",
            )

        return request_approval(
            briefing=decision,
            bot_token=self._tg_token,
            chat_id=self._tg_chat_id,
            timeout_seconds=self.telegram_timeout,
        )

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self, skip_heartbeat: bool = False) -> dict:
        """
        Runs a full cycle:
          1. Heartbeat
          2. Investigator (data collection + Flash synthesis)
          3. Manager (Pro decision)
          4. Telegram (human approval per decision)
          5. Hyperliquid (execution of approved orders)
          6. Logging

        Returns:
            Dict with the full cycle result.
        """
        cycle_start = datetime.now(timezone.utc).isoformat()
        print(f"\n{'='*60}")
        print(f"[Orchestrator] Cycle started: {cycle_start}")
        print(f"[Orchestrator] Watchlist: {self.watchlist}")
        print(f"{'='*60}")

        results: dict = {
            "cycle_start":     cycle_start,
            "watchlist":       self.watchlist,
            "errors":          [],
            "executed_orders": [],
        }

        # ── 1. Heartbeat ─────────────────────────────────────────────
        if not skip_heartbeat:
            print("\n[Orchestrator] Running heartbeat...")
            hb = self._heartbeat()
            results["heartbeat"] = hb
            if not hb["healthy"]:
                msg = f"Heartbeat failed: {hb['checks']}"
                print(f"[Orchestrator] ERROR — {msg}")
                results["errors"].append(msg)
                results["status"] = "HALTED"
                _append_to_log("cycles-log.json", results)
                return results
            print("[Orchestrator] Heartbeat OK")

        # ── 2. Investigator ──────────────────────────────────────────
        print("\n[Orchestrator] Running investigator agent...")
        try:
            investigator_output = self.investigator.run(watchlist=self.watchlist)
            briefing = investigator_output["briefing"]
            results["investigator"] = {
                "overall_bias":    briefing.get("overall_bias"),
                "bias_confidence": briefing.get("bias_confidence"),
                "macro_summary":   briefing.get("macro_summary"),
                "risk_factors":    briefing.get("risk_factors", []),
                "opportunities":   briefing.get("opportunities", []),
                "assets_ranked":   briefing.get("assets_ranked", []),
            }
            print(f"[Orchestrator] Bias: {briefing.get('overall_bias')} "
                  f"(conf={briefing.get('bias_confidence', 0):.2f})")
        except Exception as e:
            err = f"Investigator failed: {e}\n{traceback.format_exc()}"
            print(f"[Orchestrator] ERROR — {e}")
            results["errors"].append(err)
            results["status"] = "HALTED"
            _append_to_log("cycles-log.json", results)
            return results

        time.sleep(2)

        # ── 3. Current prices ────────────────────────────────────────
        print("\n[Orchestrator] Fetching current prices (CoinGecko)...")
        market_prices = self._get_current_prices()
        results["market_prices"] = market_prices

        # ── 4. Manager ───────────────────────────────────────────────
        print("\n[Orchestrator] Running manager agent (Gemini Pro)...")
        open_positions = len(self.executor.get_open_positions())
        try:
            manager_output = self.manager.run(
                investigator_output=investigator_output,
                market_prices=market_prices,
                open_positions=open_positions,
            )
            results["manager"] = {
                "decisions":  manager_output["decisions"],
                "actionable": manager_output["actionable"],
            }
            print(f"[Orchestrator] {len(manager_output['actionable'])} actionable decision(s)")
        except Exception as e:
            err = f"Manager failed: {e}\n{traceback.format_exc()}"
            print(f"[Orchestrator] ERROR — {e}")
            results["errors"].append(err)
            results["status"] = "OK_WITH_ERRORS"
            results["cycle_end"] = datetime.now(timezone.utc).isoformat()
            _append_to_log("cycles-log.json", results)
            return results

        # ── 5. Telegram approval + Execution ─────────────────────────
        actionable = manager_output.get("actionable", [])
        approvals: list[dict] = []

        if not actionable:
            print("\n[Orchestrator] No actionable decisions — HOLD on all assets")
            bias = briefing.get("overall_bias", "Neutral")
            conf = briefing.get("bias_confidence", 0)
            send_notification(
                text=(
                    f"*ClawCapital — Cycle {cycle_start[:10]}*\n"
                    f"Bias: {bias} (conf={conf:.0%})\n"
                    f"No entries — HOLD on all assets."
                ),
                bot_token=self._tg_token,
                chat_id=self._tg_chat_id,
            )
        else:
            print(f"\n[Orchestrator] Processing {len(actionable)} decision(s) via Telegram...")
            for decision in actionable:
                ticker    = decision["ticker"]
                direction = decision["direction"]
                print(f"\n  [{ticker}] {direction} — awaiting human approval...")

                tg_briefing = {
                    "ticker":            ticker,
                    "direction":         direction,
                    "combined_score":    decision.get("combined_score", 0),
                    "confidence":        decision.get("confidence", 0),
                    "price":             decision.get("entry_price", 0),
                    "stop_loss_price":   decision.get("stop_loss_price", 0),
                    "position_size_usd": decision.get("position_size_usd", 0),
                    "risk_usd":          decision.get("risk_usd", 0),
                    "thesis":            decision.get("thesis", ""),
                    "macro_context":     decision.get("macro_context", ""),
                    "technical_summary": decision.get("technical_summary", ""),
                    "sentiment_summary": decision.get("sentiment_summary", ""),
                }

                approval = self._request_human_approval(tg_briefing)
                approval_dict = approval.to_dict()
                approval_dict["ticker"] = ticker
                approvals.append(approval_dict)

                if approval.approved:
                    print(f"  [{ticker}] Approved — executing on Hyperliquid...")
                    try:
                        order = self.executor.submit_order(
                            ticker=ticker,
                            side=direction.lower(),
                            size_usd=decision.get("position_size_usd", 0),
                            entry_price=decision.get("entry_price", 0),
                            stop_loss_price=decision.get("stop_loss_price", 0),
                            take_profit_price=decision.get("take_profit_price", 0),
                            notes=decision.get("thesis", "")[:100],
                        )
                        results["executed_orders"].append(order.to_dict())
                        send_notification(
                            text=(
                                f"✅ *{ticker} {direction} executed*\n"
                                f"Entry: ${order.entry_price:,.4f}\n"
                                f"Size: ${order.size_usd:,.2f}\n"
                                f"SL: ${order.stop_loss_price:,.4f} | "
                                f"TP: ${order.take_profit_price:,.4f}"
                            ),
                            bot_token=self._tg_token,
                            chat_id=self._tg_chat_id,
                        )
                    except Exception as e:
                        err = f"Execution of {ticker} failed: {e}"
                        print(f"  [{ticker}] ERROR — {e}")
                        results["errors"].append(err)
                        send_notification(
                            text=f"❌ *{ticker}* — Execution error: {e}",
                            bot_token=self._tg_token,
                            chat_id=self._tg_chat_id,
                        )
                else:
                    reason = approval.reason or f"Rejected by user ({approval.decision})"
                    print(f"  [{ticker}] Not executed — {reason}")

        results["approvals"] = approvals

        # ── 6. Summary and logging ────────────────────────────────────
        results["open_positions"] = self.executor.get_open_positions()
        results["cycle_end"]      = datetime.now(timezone.utc).isoformat()
        results["status"]         = "OK" if not results["errors"] else "OK_WITH_ERRORS"

        _append_to_log("cycles-log.json", results)
        print(f"\n[Orchestrator] Cycle complete — {results['status']} "
              f"| {len(results['executed_orders'])} order(s) executed")
        return results


# ------------------------------------------------------------------
# Direct execution (quick test in paper mode)
# ------------------------------------------------------------------

if __name__ == "__main__":
    orc = Orchestrator(
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        cryptopanic_token=os.environ["CRYPTOPANIC_TOKEN"],
        coingecko_api_key=os.environ.get("COINGECKO_API_KEY"),
        alpha_vantage_key=os.environ.get("ALPHA_VANTAGE_API_KEY"),
        fred_api_key=os.environ.get("FRED_API_KEY"),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        hl_mode=HLMode.PAPER,
        capital=float(os.environ.get("CAPITAL", "10000")),
        watchlist=os.environ.get("WATCHLIST", "BTC,ETH,SOL").split(","),
        skip_telegram=True,
    )

    output = orc.run_cycle(skip_heartbeat=False)
    print("\n" + "=" * 60)
    print("FINAL OUTPUT:")
    print(json.dumps(output, indent=2, ensure_ascii=False))
