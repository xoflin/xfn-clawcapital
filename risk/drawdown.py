"""
Risk: Drawdown Tracker
Tracks daily and total drawdown persistently across restarts.

Persists state to memory/drawdown-state.json.
Used by the Orchestrator to feed real drawdown values into RiskCalculator,
so the system halts trading when loss limits are breached.
"""

import json
from datetime import date
from pathlib import Path

DRAWDOWN_FILE = Path(__file__).parent.parent / "memory" / "drawdown-state.json"


class DrawdownTracker:
    """
    Persistent drawdown tracker. Survives process restarts.

    Args:
        initial_capital: Starting capital in USD (used only when no state file exists).
    """

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self._state = self._load()
        self._reset_daily_if_new_day()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if DRAWDOWN_FILE.exists():
            try:
                return json.loads(DRAWDOWN_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "initial_capital":     self.initial_capital,
            "peak_capital":        self.initial_capital,
            "current_capital":     self.initial_capital,
            "daily_start_capital": self.initial_capital,
            "daily_date":          date.today().isoformat(),
            "daily_pnl_usd":       0.0,
            "total_pnl_usd":       0.0,
            "total_trades":        0,
            "winning_trades":      0,
        }

    def _save(self) -> None:
        DRAWDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        DRAWDOWN_FILE.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _reset_daily_if_new_day(self) -> None:
        today = date.today().isoformat()
        if self._state.get("daily_date") != today:
            self._state["daily_date"] = today
            self._state["daily_start_capital"] = self._state["current_capital"]
            self._state["daily_pnl_usd"] = 0.0
            self._save()

    # ------------------------------------------------------------------
    # Record closed trade
    # ------------------------------------------------------------------

    def record_trade_close(self, pnl_usd: float) -> None:
        """
        Records a closed trade PnL and updates drawdown state.
        Call this every time a position is closed (SL hit, TP hit, or manual).

        Args:
            pnl_usd: Realised profit/loss in USD (negative = loss).
        """
        self._state["current_capital"] += pnl_usd
        self._state["daily_pnl_usd"]   += pnl_usd
        self._state["total_pnl_usd"]   += pnl_usd
        self._state["total_trades"]    += 1
        if pnl_usd > 0:
            self._state["winning_trades"] += 1

        # Update peak
        if self._state["current_capital"] > self._state["peak_capital"]:
            self._state["peak_capital"] = self._state["current_capital"]

        self._save()

    # ------------------------------------------------------------------
    # Drawdown metrics
    # ------------------------------------------------------------------

    @property
    def daily_drawdown_pct(self) -> float:
        """Percentage loss vs. start of today. 0 if no loss."""
        start = self._state["daily_start_capital"]
        current = self._state["current_capital"]
        if start <= 0 or current >= start:
            return 0.0
        return (start - current) / start * 100

    @property
    def total_drawdown_pct(self) -> float:
        """Percentage loss vs. peak capital (max drawdown). 0 if at peak."""
        peak = self._state["peak_capital"]
        current = self._state["current_capital"]
        if peak <= 0 or current >= peak:
            return 0.0
        return (peak - current) / peak * 100

    @property
    def current_capital(self) -> float:
        return self._state["current_capital"]

    @property
    def win_rate(self) -> float | None:
        """Historical win rate (None if no closed trades yet)."""
        total = self._state.get("total_trades", 0)
        if total == 0:
            return None
        return self._state.get("winning_trades", 0) / total

    def summary(self) -> dict:
        return {
            "current_capital":     round(self._state["current_capital"], 2),
            "peak_capital":        round(self._state["peak_capital"], 2),
            "daily_pnl_usd":       round(self._state["daily_pnl_usd"], 2),
            "daily_drawdown_pct":  round(self.daily_drawdown_pct, 4),
            "total_pnl_usd":       round(self._state["total_pnl_usd"], 2),
            "total_drawdown_pct":  round(self.total_drawdown_pct, 4),
            "total_trades":        self._state.get("total_trades", 0),
            "win_rate":            round(self.win_rate, 4) if self.win_rate is not None else None,
        }
