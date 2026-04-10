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
from risk.drawdown import DrawdownTracker
from skills.data_fetchers.coingecko import CoinGeckoClient


MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


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
        cryptopanic_token: str | None = None,   # kept for backwards compat, unused
        coingecko_api_key: str | None = None,
        alpha_vantage_key: str | None = None,
        fred_api_key: str | None = None,
        cryptocompare_api_key: str | None = None,
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
            coingecko_api_key=coingecko_api_key,
            alpha_vantage_key=alpha_vantage_key,
            fred_api_key=fred_api_key,
            cryptocompare_api_key=cryptocompare_api_key,
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
        self._drawdown   = DrawdownTracker(initial_capital=capital)

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
            from google import genai  # noqa: F401
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
    # SL/TP monitor (paper + live)
    # ------------------------------------------------------------------

    def _check_sl_tp(self, market_prices: dict[str, float]) -> list[dict]:
        """
        Checks all open positions against current prices.
        Auto-closes positions where SL or TP has been hit.
        Records PnL into DrawdownTracker.

        Returns:
            List of close records for positions that were closed.
        """
        closed = []
        for pos in self.executor.get_open_positions():
            ticker = pos["ticker"]
            price  = market_prices.get(ticker)
            if price is None:
                continue

            side = pos["side"]
            sl   = pos.get("stop_loss_price", 0)
            tp   = pos.get("take_profit_price", 0)

            hit = None
            if side == "buy":
                if sl > 0 and price <= sl:
                    hit = ("SL", sl)
                elif tp > 0 and price >= tp:
                    hit = ("TP", tp)
            else:  # sell
                if sl > 0 and price >= sl:
                    hit = ("SL", sl)
                elif tp > 0 and price <= tp:
                    hit = ("TP", tp)

            if hit:
                label, exit_price = hit
                print(f"  {ticker} {label} hit  ${exit_price:,.4f}")
                record = self.executor.close_position(ticker, exit_price)
                if record:
                    record["exit_reason"] = label
                    closed.append(record)
                    self._drawdown.record_trade_close(record["pnl_usd"])
                    send_notification(
                        text=(
                            f"{'✅' if label == 'TP' else '🛑'} "
                            f"*{ticker} {label} hit*\n"
                            f"Exit: ${exit_price:,.4f} | "
                            f"PnL: ${record['pnl_usd']:+,.2f} ({record['pnl_pct']:+.2f}%)"
                        ),
                        bot_token=self._tg_token,
                        chat_id=self._tg_chat_id,
                    )
        return closed

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
        _ts = cycle_start[:16].replace("T", "  ") + " UTC"
        _wl = " · ".join(self.watchlist)
        print(f"\n{'─'*56}")
        print(f"  ClawCapital  {_ts}  [{_wl}]")
        print(f"{'─'*56}")

        results: dict = {
            "cycle_start":     cycle_start,
            "watchlist":       self.watchlist,
            "errors":          [],
            "executed_orders": [],
        }

        # ── 1. Heartbeat ─────────────────────────────────────────────
        if not skip_heartbeat:
            hb = self._heartbeat()
            results["heartbeat"] = hb
            if not hb["healthy"]:
                failed = [k for k, v in hb["checks"].items() if not v]
                print(f"  Heartbeat    ✗  {', '.join(failed)} unreachable — halting")
                results["errors"].append(f"Heartbeat failed: {hb['checks']}")
                results["status"] = "HALTED"
                _append_to_log("cycles-log.json", results)
                return results
            ok_services = " + ".join(k for k, v in hb["checks"].items() if v)
            print(f"  Heartbeat    ✓  {ok_services}")

        # ── 1b. Cold-start checks (balance + reconciliation) ─────────
        effective_capital = self.capital
        real_balance = self.executor.get_available_balance()
        if real_balance is not None:
            effective_capital = real_balance
            print(f"  Balance      ✓  ${real_balance:,.2f}")
            results["real_balance"] = real_balance

        trades_path = MEMORY_DIR / "trades-history.json"
        is_cold_start = not trades_path.exists() or trades_path.stat().st_size < 10
        open_pos_count = len(self.executor.get_open_positions())
        dd = self._drawdown
        cold_tag = "  ⚡ cold start — conservative sizing" if is_cold_start else ""
        print(f"  Positions    ✓  {open_pos_count} open  |  DD daily={dd.daily_drawdown_pct:.2f}%  total={dd.total_drawdown_pct:.2f}%{cold_tag}")
        results["is_cold_start"] = is_cold_start

        unknown_positions = self.executor.reconcile_positions()
        if unknown_positions:
            tickers = [p.get("coin") for p in unknown_positions]
            print(f"  Reconcile    ⚠  {len(unknown_positions)} untracked position(s) on exchange: {tickers}")
            results["untracked_positions"] = unknown_positions

        # ── 2. Investigator ──────────────────────────────────────────
        print("")
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
        except Exception as e:
            print(f"  [Investigator] ERROR — {e}")
            results["errors"].append(f"Investigator failed: {e}\n{traceback.format_exc()}")
            results["status"] = "HALTED"
            _append_to_log("cycles-log.json", results)
            return results

        time.sleep(2)

        # ── 3. Current prices + SL/TP check ─────────────────────────
        market_prices = self._get_current_prices()
        results["market_prices"] = market_prices

        sl_tp_closes = self._check_sl_tp(market_prices)
        if sl_tp_closes:
            results["sl_tp_closes"] = sl_tp_closes

        results["drawdown"] = self._drawdown.summary()

        # ── 4. Manager ───────────────────────────────────────────────
        print("")
        open_positions = len(self.executor.get_open_positions())
        try:
            manager_output = self.manager.run(
                investigator_output=investigator_output,
                market_prices=market_prices,
                open_positions=open_positions,
                daily_drawdown_pct=self._drawdown.daily_drawdown_pct,
                total_drawdown_pct=self._drawdown.total_drawdown_pct,
                effective_capital=effective_capital,
                is_cold_start=is_cold_start,
            )
            actionable = manager_output.get("actionable", [])
            results["manager"] = {
                "decisions":  manager_output["decisions"],
                "actionable": [d.to_dict() for d in actionable],
            }
        except Exception as e:
            print(f"  [Manager] ERROR — {e}")
            results["errors"].append(f"Manager failed: {e}\n{traceback.format_exc()}")
            results["status"] = "OK_WITH_ERRORS"
            results["cycle_end"] = datetime.now(timezone.utc).isoformat()
            _append_to_log("cycles-log.json", results)
            return results

        # ── 5. Telegram approval + Execution ─────────────────────────
        approvals: list[dict] = []
        print("")

        if not actionable:
            bias = briefing.get("overall_bias", "Neutral")
            conf = briefing.get("bias_confidence", 0)
            print(f"  No entries — HOLD all  ({bias}  conf={conf:.2f})")
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
            print(f"  {len(actionable)} actionable — awaiting Telegram approval")
            for decision in actionable:
                ticker    = decision.ticker
                direction = decision.direction

                approval = self._request_human_approval(decision.to_telegram_briefing())
                approval_dict = approval.to_dict()
                approval_dict["ticker"] = ticker
                approvals.append(approval_dict)

                if approval.approved:
                    try:
                        order = self.executor.submit_order(
                            ticker=ticker,
                            side=direction.lower(),
                            size_usd=decision.position_size_usd,
                            entry_price=decision.entry_price,
                            stop_loss_price=decision.stop_loss_price,
                            take_profit_price=decision.take_profit_price,
                            notes=decision.thesis[:100],
                        )
                        results["executed_orders"].append(order.to_dict())
                        print(
                            f"  ✓ {ticker} {direction} submitted  "
                            f"size=${order.size_usd:,.0f}  "
                            f"SL=${order.stop_loss_price:,.0f}  TP=${order.take_profit_price:,.0f}"
                        )
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
                        print(f"  ✗ {ticker} — execution error: {e}")
                        results["errors"].append(f"Execution of {ticker} failed: {e}")
                        send_notification(
                            text=f"❌ *{ticker}* — Execution error: {e}",
                            bot_token=self._tg_token,
                            chat_id=self._tg_chat_id,
                        )
                else:
                    reason = approval.reason or f"rejected ({approval.decision})"
                    print(f"  ✗ {ticker} — {reason}")

        results["approvals"] = approvals

        # ── 6. Summary and logging ────────────────────────────────────
        results["open_positions"] = self.executor.get_open_positions()
        results["drawdown"]       = self._drawdown.summary()
        results["quota"]          = self.manager._quota.summary()
        results["cycle_end"]      = datetime.now(timezone.utc).isoformat()
        results["status"]         = "OK" if not results["errors"] else "OK_WITH_ERRORS"

        _append_to_log("cycles-log.json", results)
        n_orders = len(results["executed_orders"])
        print(f"\n{'─'*56}")
        print(f"  Done  {results['status']}  |  {n_orders} order(s)")
        print(f"{'─'*56}")
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
