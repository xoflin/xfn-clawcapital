"""
Risk Manager — Position Calculator
Validates decisions and computes position size before any execution.

Delegates math to skills:
  - skills.sizing.kelly            → Kelly criterion
  - skills.sizing.fixed_fractional → fixed risk per trade
"""

from dataclasses import dataclass, field
from enum import Enum

from skills.sizing import kelly as kelly_skill
from skills.sizing import fixed_fractional as ff_skill


# ------------------------------------------------------------------
# Risk configuration
# ------------------------------------------------------------------

@dataclass
class RiskConfig:
    """Global risk parameters for the system."""

    max_risk_per_trade_pct: float = 1.0       # 1%
    max_allocation_per_asset_pct: float = 2.0 # 2%
    max_daily_drawdown_pct: float = 3.0       # 3%
    max_total_drawdown_pct: float = 10.0      # 10%
    max_open_positions: int = 5
    kelly_fraction: float = 0.5
    min_confidence_threshold: float = 0.60


class SizingMethod(Enum):
    FIXED_FRACTIONAL = "fixed_fractional"
    KELLY            = "kelly"
    HYBRID           = "hybrid"


# ------------------------------------------------------------------
# Output type
# ------------------------------------------------------------------

@dataclass
class PositionResult:
    method: str
    ticker: str
    capital: float
    entry_price: float
    stop_loss_price: float
    risk_reward_ratio: float
    confidence: float

    position_size_usd: float
    position_size_units: float
    risk_amount_usd: float
    stop_loss_pct: float
    take_profit_price: float
    approved: bool
    rejection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "module":            "risk-manager",
            "method":            self.method,
            "ticker":            self.ticker,
            "approved":          self.approved,
            "rejection_reasons": self.rejection_reasons,
            "position": {
                "size_usd":      round(self.position_size_usd, 2),
                "size_units":    round(self.position_size_units, 8),
                "risk_usd":      round(self.risk_amount_usd, 2),
                "entry_price":   self.entry_price,
                "stop_loss":     round(self.stop_loss_price, 6),
                "take_profit":   round(self.take_profit_price, 6),
                "stop_loss_pct": round(self.stop_loss_pct, 4),
                "risk_reward":   self.risk_reward_ratio,
            },
            "inputs": {
                "capital":    self.capital,
                "confidence": self.confidence,
            },
        }


# ------------------------------------------------------------------
# Risk Calculator
# ------------------------------------------------------------------

class RiskCalculator:
    """
    Computes the optimal position size and validates risk rules
    before any order is executed.
    """

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()

    def calculate_position(
        self,
        ticker: str,
        capital: float,
        entry_price: float,
        stop_loss_price: float,
        confidence: float,
        risk_reward_ratio: float = 2.0,
        method: SizingMethod = SizingMethod.HYBRID,
        win_rate: float | None = None,
        avg_win_pct: float | None = None,
        avg_loss_pct: float | None = None,
        current_open_positions: int = 0,
        current_daily_drawdown_pct: float = 0.0,
        current_total_drawdown_pct: float = 0.0,
        is_cold_start: bool = False,
    ) -> PositionResult:
        """
        Computes position size and validates risk rules.

        Args:
            is_cold_start: True when there is no trade history.
                           Applies conservative sizing (half Kelly, half risk cap)
                           to protect capital on the very first position.

        Rules checked:
        - Minimum agent confidence
        - Daily and total drawdown
        - Maximum open positions
        - Maximum allocation per asset
        - Valid stop loss (> 0 and < entry)
        """
        rejection_reasons: list[str] = []

        if stop_loss_price <= 0 or stop_loss_price >= entry_price:
            rejection_reasons.append(
                f"Invalid stop loss: {stop_loss_price} must be > 0 and < entry {entry_price}"
            )

        if confidence < self.config.min_confidence_threshold:
            rejection_reasons.append(
                f"Confidence {confidence:.0%} below minimum "
                f"{self.config.min_confidence_threshold:.0%}"
            )

        if current_daily_drawdown_pct >= self.config.max_daily_drawdown_pct:
            rejection_reasons.append(
                f"Daily drawdown {current_daily_drawdown_pct:.2f}% reached limit "
                f"{self.config.max_daily_drawdown_pct:.2f}%"
            )

        if current_total_drawdown_pct >= self.config.max_total_drawdown_pct:
            rejection_reasons.append(
                f"Total drawdown {current_total_drawdown_pct:.2f}% reached limit "
                f"{self.config.max_total_drawdown_pct:.2f}%"
            )

        if current_open_positions >= self.config.max_open_positions:
            rejection_reasons.append(
                f"Maximum open positions reached ({self.config.max_open_positions})"
            )

        # ---- Position sizing ----
        # Ponto 2: Cold start — sem histórico de trades, sizing conservador
        # Usa metade da kelly_fraction e metade do max_risk para proteger capital
        # na primeira posição onde não há win rate histórico para calibrar Kelly.
        effective_kelly_fraction = (
            self.config.kelly_fraction * 0.5 if is_cold_start
            else self.config.kelly_fraction
        )
        effective_max_risk_pct = (
            self.config.max_risk_per_trade_pct * 0.5 if is_cold_start
            else self.config.max_risk_per_trade_pct
        )
        if is_cold_start:
            print(f"  [RiskCalc] Cold start detected — using conservative sizing "
                  f"(kelly×0.5, risk_pct×0.5 → {effective_max_risk_pct:.2f}%)")

        stop_loss_pct = abs((entry_price - stop_loss_price) / entry_price) * 100
        max_risk_usd  = ff_skill.risk_amount(capital, effective_max_risk_pct)

        if method == SizingMethod.FIXED_FRACTIONAL:
            risk_usd = max_risk_usd

        elif method == SizingMethod.KELLY:
            if all(v is not None for v in [win_rate, avg_win_pct, avg_loss_pct]):
                frac     = kelly_skill.fractional_kelly(win_rate, avg_win_pct, avg_loss_pct, effective_kelly_fraction)
                risk_usd = capital * frac
            else:
                risk_usd = max_risk_usd

        else:  # HYBRID
            if all(v is not None for v in [win_rate, avg_win_pct, avg_loss_pct]):
                frac     = kelly_skill.fractional_kelly(win_rate, avg_win_pct, avg_loss_pct, effective_kelly_fraction)
                risk_usd = min(capital * frac, max_risk_usd)
            else:
                risk_usd = max_risk_usd

        risk_usd *= confidence

        position_size_usd   = ff_skill.position_size_from_risk(risk_usd, stop_loss_pct)
        max_allocation_usd  = capital * (self.config.max_allocation_per_asset_pct / 100)
        if position_size_usd > max_allocation_usd:
            position_size_usd = max_allocation_usd

        risk_amount_usd      = position_size_usd * (stop_loss_pct / 100) if stop_loss_pct > 0 else 0.0
        position_size_units  = position_size_usd / entry_price if entry_price > 0 else 0.0
        price_range          = entry_price - stop_loss_price
        take_profit_price    = entry_price + (price_range * risk_reward_ratio)

        return PositionResult(
            method=method.value,
            ticker=ticker,
            capital=capital,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            risk_reward_ratio=risk_reward_ratio,
            confidence=confidence,
            position_size_usd=position_size_usd,
            position_size_units=position_size_units,
            risk_amount_usd=risk_amount_usd,
            stop_loss_pct=stop_loss_pct,
            take_profit_price=take_profit_price,
            approved=len(rejection_reasons) == 0,
            rejection_reasons=rejection_reasons,
        )

    def can_trade(
        self,
        confidence: float,
        current_open_positions: int = 0,
        current_daily_drawdown_pct: float = 0.0,
        current_total_drawdown_pct: float = 0.0,
    ) -> tuple[bool, list[str]]:
        """Quick check whether the system is in a state to trade."""
        reasons = []
        if confidence < self.config.min_confidence_threshold:
            reasons.append(f"Insufficient confidence: {confidence:.0%}")
        if current_daily_drawdown_pct >= self.config.max_daily_drawdown_pct:
            reasons.append(f"Daily drawdown at limit: {current_daily_drawdown_pct:.2f}%")
        if current_total_drawdown_pct >= self.config.max_total_drawdown_pct:
            reasons.append(f"Total drawdown at limit: {current_total_drawdown_pct:.2f}%")
        if current_open_positions >= self.config.max_open_positions:
            reasons.append(f"Open positions at maximum: {current_open_positions}")
        return len(reasons) == 0, reasons

    def portfolio_summary(
        self,
        capital: float,
        open_positions: list[dict],
    ) -> dict:
        """Summarises current portfolio exposure."""
        total_allocated = sum(p.get("size_usd", 0) for p in open_positions)
        total_risk      = sum(p.get("risk_usd", 0) for p in open_positions)
        allocated_pct   = (total_allocated / capital * 100) if capital > 0 else 0
        risk_pct        = (total_risk / capital * 100) if capital > 0 else 0

        return {
            "capital":               capital,
            "open_positions":        len(open_positions),
            "total_allocated_usd":   round(total_allocated, 2),
            "total_allocated_pct":   round(allocated_pct, 4),
            "total_risk_usd":        round(total_risk, 2),
            "total_risk_pct":        round(risk_pct, 4),
            "remaining_capital_usd": round(capital - total_allocated, 2),
            "slots_available":       max(0, self.config.max_open_positions - len(open_positions)),
        }


# ------------------------------------------------------------------
# Direct execution (test/debug)
# ------------------------------------------------------------------

if __name__ == "__main__":
    import json

    config = RiskConfig(
        max_risk_per_trade_pct=1.0,
        max_allocation_per_asset_pct=2.0,
        max_daily_drawdown_pct=3.0,
        max_total_drawdown_pct=10.0,
        max_open_positions=5,
        kelly_fraction=0.5,
        min_confidence_threshold=0.60,
    )

    calc = RiskCalculator(config=config)

    print("=== Position Calculation — BTC (Hybrid Kelly) ===")
    result = calc.calculate_position(
        ticker="BTC",
        capital=10_000,
        entry_price=65_000,
        stop_loss_price=63_000,
        confidence=0.82,
        risk_reward_ratio=2.0,
        method=SizingMethod.HYBRID,
        win_rate=0.55,
        avg_win_pct=3.0,
        avg_loss_pct=1.5,
        current_open_positions=2,
    )
    print(json.dumps(result.to_dict(), indent=2))
