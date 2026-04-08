"""
Agent: Manager — Final Decision Maker
Uses Gemini 2.5 Pro to decide direction and price levels.
RiskCalculator handles all position sizing and risk veto rules.

Quota: 100 req/day — each call to run() consumes 1 req.

Input:  briefing dict from InvestigatorAgent + risk parameters
Output: list of ManagerDecision per ticker, ready for Telegram + executor
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import google.generativeai as genai

from risk.calculator import RiskCalculator, RiskConfig, SizingMethod


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

_MODEL_NAME = "gemini-2.5-pro-preview-05-06"


# ------------------------------------------------------------------
# Output type
# ------------------------------------------------------------------

@dataclass
class ManagerDecision:
    ticker: str
    direction: str                    # "BUY" | "SELL" | "HOLD"
    conviction: float                 # 0.0 – 1.0
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    position_size_usd: float
    risk_usd: float
    thesis: str
    macro_context: str
    technical_summary: str
    sentiment_summary: str
    combined_score: float
    confidence: float
    rejected: bool = False
    rejection_reason: str = ""
    decided_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "ticker":             self.ticker,
            "direction":          self.direction,
            "conviction":         self.conviction,
            "entry_price":        self.entry_price,
            "stop_loss_price":    self.stop_loss_price,
            "take_profit_price":  self.take_profit_price,
            "position_size_usd":  self.position_size_usd,
            "risk_usd":           self.risk_usd,
            "thesis":             self.thesis,
            "macro_context":      self.macro_context,
            "technical_summary":  self.technical_summary,
            "sentiment_summary":  self.sentiment_summary,
            "combined_score":     self.combined_score,
            "confidence":         self.confidence,
            "rejected":           self.rejected,
            "rejection_reason":   self.rejection_reason,
            "decided_at":         self.decided_at,
        }

    def to_telegram_briefing(self) -> dict:
        """Format accepted by notifications.telegram.request_approval()."""
        return {
            "ticker":            self.ticker,
            "direction":         self.direction,
            "combined_score":    self.combined_score,
            "confidence":        self.confidence,
            "price":             self.entry_price,
            "stop_loss_price":   self.stop_loss_price,
            "position_size_usd": self.position_size_usd,
            "risk_usd":          self.risk_usd,
            "thesis":            self.thesis,
            "macro_context":     self.macro_context,
            "technical_summary": self.technical_summary,
            "sentiment_summary": self.sentiment_summary,
        }


# ------------------------------------------------------------------
# Manager prompt — asks only for direction + price levels
# Position sizing is handled by RiskCalculator, not Gemini
# ------------------------------------------------------------------

_MANAGER_PROMPT = """\
You are a senior quantitative portfolio manager focused on capital preservation.
Your sole function is to make definitive investment decisions based on the investigator's briefing.

=== INVESTIGATOR BRIEFING ===
{briefing_json}

=== RISK PARAMETERS ===
Total available capital: ${capital:,.2f}
Maximum risk per trade: {max_risk_pct:.1f}% of capital
Default stop loss: {stop_loss_pct:.1f}% below entry (BUY) or above (SELL)
Minimum risk/reward ratio: {risk_reward_ratio:.1f}:1
Minimum confidence for entry: {min_confidence:.0%}
Currently open positions: {open_positions} / {max_positions}

=== CURRENT MARKET PRICES ===
{market_prices}

---
Non-negotiable principles:
1. Capital preservation is the absolute priority.
2. When in doubt, HOLD is always the correct decision.
3. Never enter a trade purely on momentum — require signal confluence.
4. A rejected trade that would have been profitable is far less damaging than a loss.

For each asset in assets_ranked, decide BUY, SELL or HOLD.
Set entry_price and stop_loss_price based on market structure — do NOT compute position size.

Respond with JSON ONLY:

[
  {{
    "ticker": "<TICKER>",
    "direction": "<BUY|SELL|HOLD>",
    "conviction": <0.0 to 1.0>,
    "entry_price": <current asset price>,
    "stop_loss_price": <stop loss price — technical level>,
    "thesis": "<investment thesis in 1-2 direct sentences>",
    "rejection_reason": "<reason if HOLD, empty string if BUY/SELL>"
  }}
]

No additional text. No markdown. JSON array only.
"""


# ------------------------------------------------------------------
# Manager Agent
# ------------------------------------------------------------------

class ManagerAgent:
    """
    Makes final investment decisions using Gemini 2.5 Pro.
    RiskCalculator handles position sizing and risk veto rules.

    Args:
        gemini_api_key:    Gemini API key (Pro).
        capital:           Total available capital in USD.
        max_risk_pct:      Maximum % of capital to risk per trade (default 1%).
        stop_loss_pct:     Default stop loss % (default 3%).
        risk_reward_ratio: Minimum risk/reward ratio (default 2.0).
        min_confidence:    Minimum confidence to generate BUY/SELL (default 0.60).
        max_positions:     Maximum simultaneous open positions (default 5).
    """

    def __init__(
        self,
        gemini_api_key: str,
        capital: float = 10_000.0,
        max_risk_pct: float = 1.0,
        stop_loss_pct: float = 3.0,
        risk_reward_ratio: float = 2.0,
        min_confidence: float = 0.60,
        max_positions: int = 5,
    ):
        self.capital = capital
        self.stop_loss_pct = stop_loss_pct
        self.risk_reward_ratio = risk_reward_ratio
        self.min_confidence = min_confidence
        self.max_positions = max_positions

        genai.configure(api_key=gemini_api_key)
        self._model = genai.GenerativeModel(_MODEL_NAME)

        self._risk = RiskCalculator(RiskConfig(
            max_risk_per_trade_pct=max_risk_pct,
            max_open_positions=max_positions,
            min_confidence_threshold=min_confidence,
        ))

    # ------------------------------------------------------------------
    # Decision via Gemini Pro
    # ------------------------------------------------------------------

    def _decide(
        self,
        investigator_output: dict,
        market_prices: dict[str, float],
        open_positions: int,
    ) -> list[dict]:
        """Calls Gemini 2.5 Pro and returns raw directional decisions."""
        briefing = investigator_output.get("briefing", {})

        prices_str = "\n".join(
            f"  {ticker}: ${price:,.4f}"
            for ticker, price in market_prices.items()
        )

        prompt = _MANAGER_PROMPT.format(
            briefing_json=json.dumps(briefing, ensure_ascii=False, indent=2),
            capital=self.capital,
            max_risk_pct=self._risk.config.max_risk_per_trade_pct,
            stop_loss_pct=self.stop_loss_pct,
            risk_reward_ratio=self.risk_reward_ratio,
            min_confidence=self.min_confidence,
            open_positions=open_positions,
            max_positions=self.max_positions,
            market_prices=prices_str,
        )

        response = self._model.generate_content(prompt)
        raw = response.text.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError(f"Expected JSON array from Gemini, got: {type(parsed)}")
        return parsed

    # ------------------------------------------------------------------
    # Build ManagerDecision using RiskCalculator for sizing
    # ------------------------------------------------------------------

    def _build_decisions(
        self,
        raw_decisions: list[dict],
        investigator_output: dict,
        market_prices: dict[str, float],
        open_positions: int,
        daily_drawdown_pct: float = 0.0,
        total_drawdown_pct: float = 0.0,
    ) -> list[ManagerDecision]:
        briefing        = investigator_output.get("briefing", {})
        bias_confidence = float(briefing.get("bias_confidence", 0.0))
        macro_summary   = briefing.get("macro_summary", "")
        tech_summary    = briefing.get("technical_summary", "")
        sent_summary    = briefing.get("sentiment_summary", "")

        decisions = []
        for raw in raw_decisions:
            ticker     = raw.get("ticker", "?").upper()
            direction  = raw.get("direction", "HOLD").upper()
            conviction = float(raw.get("conviction", 0.0))
            entry      = float(raw.get("entry_price", market_prices.get(ticker, 0)))
            stop       = float(raw.get("stop_loss_price", 0))
            thesis     = raw.get("thesis", "")
            rej_reason = raw.get("rejection_reason", "")

            # Confidence: conviction weighted by investigator's bias quality
            # Formula prevents double-penalty: even low bias_confidence preserves 50% of conviction
            confidence     = conviction * (0.5 + bias_confidence * 0.5)
            combined_score = conviction * (1 if direction == "BUY" else -1 if direction == "SELL" else 0)

            if direction not in ("BUY", "SELL"):
                decisions.append(ManagerDecision(
                    ticker=ticker, direction="HOLD", conviction=conviction,
                    entry_price=entry, stop_loss_price=stop, take_profit_price=0.0,
                    position_size_usd=0.0, risk_usd=0.0, thesis=thesis,
                    macro_context=macro_summary, technical_summary=tech_summary,
                    sentiment_summary=sent_summary, combined_score=0.0,
                    confidence=round(confidence, 4), rejected=False,
                    rejection_reason=rej_reason,
                ))
                continue

            # RiskCalculator: sizing + veto rules (real drawdown values)
            pos = self._risk.calculate_position(
                ticker=ticker,
                capital=self.capital,
                entry_price=entry,
                stop_loss_price=stop,
                confidence=round(confidence, 4),
                risk_reward_ratio=self.risk_reward_ratio,
                method=SizingMethod.HYBRID,
                current_open_positions=open_positions,
                current_daily_drawdown_pct=daily_drawdown_pct,
                current_total_drawdown_pct=total_drawdown_pct,
            )

            if not pos.approved:
                rejection = "; ".join(pos.rejection_reasons)
            else:
                rejection = ""

            decisions.append(ManagerDecision(
                ticker=ticker,
                direction="HOLD" if not pos.approved else direction,
                conviction=conviction,
                entry_price=entry,
                stop_loss_price=pos.stop_loss_price,
                take_profit_price=pos.take_profit_price,
                position_size_usd=pos.position_size_usd if pos.approved else 0.0,
                risk_usd=pos.risk_amount_usd if pos.approved else 0.0,
                thesis=thesis,
                macro_context=macro_summary,
                technical_summary=tech_summary,
                sentiment_summary=sent_summary,
                combined_score=round(combined_score, 4),
                confidence=round(confidence, 4),
                rejected=not pos.approved,
                rejection_reason=rejection,
            ))

        return decisions

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        investigator_output: dict,
        market_prices: dict[str, float],
        open_positions: int = 0,
        daily_drawdown_pct: float = 0.0,
        total_drawdown_pct: float = 0.0,
    ) -> dict:
        """
        Makes investment decisions based on the investigator's output.

        Args:
            investigator_output: Full output from InvestigatorAgent.run().
            market_prices:       {ticker: current_price} for each asset.
            open_positions:      Number of currently open positions.

        Returns:
            {
              "agent": "manager",
              "timestamp": str,
              "gemini_model": str,
              "decisions": [ManagerDecision.to_dict(), ...],
              "actionable": [ManagerDecision, ...]  ← objects for orchestrator
            }
        """
        print("[Manager] Analysing briefing with Gemini 2.5 Pro...")
        ts = datetime.now(timezone.utc).isoformat()

        try:
            raw_decisions = self._decide(investigator_output, market_prices, open_positions)
        except Exception as e:
            print(f"[Manager] ERROR — Gemini Pro failed: {e}")
            return {
                "agent":        "manager",
                "timestamp":    ts,
                "gemini_model": _MODEL_NAME,
                "decisions":    [],
                "actionable":   [],
                "error":        str(e),
            }

        decisions  = self._build_decisions(
            raw_decisions, investigator_output, market_prices,
            open_positions, daily_drawdown_pct, total_drawdown_pct,
        )
        actionable = [d for d in decisions if d.direction in ("BUY", "SELL") and not d.rejected]

        for d in decisions:
            status = "✓" if not d.rejected else "✗"
            print(f"[Manager] {status} {d.ticker}: {d.direction} "
                  f"(conviction={d.conviction:.2f}, confidence={d.confidence:.2f})"
                  + (f" — {d.rejection_reason}" if d.rejected else ""))

        print(f"[Manager] {len(actionable)}/{len(decisions)} actionable decisions")

        return {
            "agent":        "manager",
            "timestamp":    ts,
            "gemini_model": _MODEL_NAME,
            "decisions":    [d.to_dict() for d in decisions],
            "actionable":   actionable,  # ManagerDecision objects — orchestrator calls .to_telegram_briefing()
        }


# ------------------------------------------------------------------
# Direct execution (test/debug)
# ------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    _sample = {
        "agent": "investigator",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "watchlist": ["BTC", "ETH"],
        "briefing": {
            "macro_summary":     "Fed holding rates high. CPI declining gradually.",
            "market_summary":    "BTC consolidating above $60k. ETH following.",
            "technical_summary": "RSI neutral. MACD positive crossover on BTC.",
            "sentiment_summary": "Mixed sentiment. Positive ETF inflow news.",
            "risk_factors":      ["Regulatory risk", "Macro volatility"],
            "opportunities":     ["ETF inflows", "Halving momentum"],
            "overall_bias":      "Bullish",
            "bias_confidence":   0.72,
            "assets_ranked": [
                {
                    "ticker":          "BTC",
                    "thesis":          "Post-halving momentum with institutional support via ETFs.",
                    "technical_score": 0.6,
                    "sentiment_score": 0.5,
                    "priority":        1,
                },
                {
                    "ticker":          "ETH",
                    "thesis":          "Growing TVL and spot ETF expectations.",
                    "technical_score": 0.4,
                    "sentiment_score": 0.4,
                    "priority":        2,
                },
            ],
            "investigator_notes": "Low volatility period — good for partial entries.",
        },
    }

    agent = ManagerAgent(
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        capital=10_000.0,
        max_risk_pct=1.0,
        stop_loss_pct=3.0,
        risk_reward_ratio=2.0,
        min_confidence=0.60,
    )

    result = agent.run(
        investigator_output=_sample,
        market_prices={"BTC": 65000.0, "ETH": 3200.0},
        open_positions=0,
    )

    print("\n=== DECISIONS ===")
    print(json.dumps([d.to_dict() if hasattr(d, "to_dict") else d for d in result["actionable"]], indent=2, ensure_ascii=False))
