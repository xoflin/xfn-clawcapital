"""
Skill: learning/trade_analyzer
Analyses historical trades to extract performance patterns and lessons.

Reads memory files (closed-trades.json, cycles-log.json, trades-history.json)
and produces structured insights that are injected back into agent prompts,
allowing the system to learn from its own decisions.

Output:  memory/lessons.json  — persisted learning state
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"
LESSONS_FILE = MEMORY_DIR / "lessons.json"


def _load_json(filename: str) -> list:
    path = MEMORY_DIR / filename
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def analyze() -> dict:
    """
    Analyses all historical trade data and generates structured lessons.

    Returns:
        {
            "total_trades": int,
            "win_rate": float (0-1),
            "total_pnl_usd": float,
            "avg_pnl_usd": float,
            "best_trade": {...},
            "worst_trade": {...},
            "by_ticker": {
                "BTC": {"trades": N, "win_rate": 0.X, "avg_pnl": Y, "total_pnl": Z},
                ...
            },
            "by_direction": {
                "BUY": {"trades": N, "win_rate": 0.X, "avg_pnl": Y},
                "SELL": {"trades": N, "win_rate": 0.X, "avg_pnl": Y},
            },
            "by_confidence_band": {
                "0.50-0.60": {"trades": N, "win_rate": 0.X},
                "0.60-0.70": {"trades": N, "win_rate": 0.X},
                ...
            },
            "patterns": [str, ...],       # human-readable lessons
            "prompt_context": str,         # formatted for LLM injection
            "analyzed_at": str,
        }
    """
    closed  = _load_json("closed-trades.json")
    history = _load_json("trades-history.json")
    cycles  = _load_json("cycles-log.json")

    if not closed:
        return _empty_report()

    # Build lookup: order_id → trade details from history
    history_map = {}
    for t in history:
        oid = t.get("order_id") or t.get("id")
        if oid:
            history_map[oid] = t

    # Build lookup: cycle_start → cycle decisions
    cycle_decisions = {}
    for c in cycles:
        ts = c.get("cycle_start", "")
        manager = c.get("manager", {})
        for d in manager.get("decisions", []):
            ticker = d.get("ticker", "")
            key = f"{ts}_{ticker}"
            cycle_decisions[key] = d

    # ── Aggregate stats ───────────────────────────────────────────
    total_pnl = 0.0
    wins      = 0
    by_ticker:     dict[str, list] = defaultdict(list)
    by_direction:  dict[str, list] = defaultdict(list)
    by_conf_band:  dict[str, list] = defaultdict(list)
    all_trades: list[dict] = []

    for trade in closed:
        pnl    = float(trade.get("pnl_usd", 0))
        ticker = trade.get("ticker", "?")
        oid    = trade.get("order_id", "")

        # Enrich with original trade data
        orig = history_map.get(oid, {})
        side = orig.get("side", trade.get("side", "?"))
        conf = float(orig.get("confidence", 0) or 0)

        # Find matching cycle decision for conviction data
        # (approximate match by iterating recent cycles)
        conviction = 0.0
        for cd in cycle_decisions.values():
            if cd.get("ticker") == ticker:
                conviction = float(cd.get("conviction", 0))
                if conf == 0:
                    conf = float(cd.get("confidence", 0))

        record = {
            "ticker":     ticker,
            "side":       side,
            "pnl_usd":    pnl,
            "pnl_pct":    float(trade.get("pnl_pct", 0)),
            "confidence": conf,
            "conviction": conviction,
            "exit_reason": trade.get("exit_reason", ""),
            "closed_at":  trade.get("closed_at", ""),
        }
        all_trades.append(record)

        total_pnl += pnl
        if pnl > 0:
            wins += 1

        by_ticker[ticker].append(record)
        by_direction[side.upper()].append(record)

        # Confidence bands: 0.40-0.50, 0.50-0.60, etc.
        band_low  = math.floor(conf * 10) / 10
        band_high = band_low + 0.10
        band_key  = f"{band_low:.2f}-{band_high:.2f}"
        by_conf_band[band_key].append(record)

    n = len(all_trades)
    win_rate = wins / n if n else 0
    avg_pnl  = total_pnl / n if n else 0

    best  = max(all_trades, key=lambda t: t["pnl_usd"]) if all_trades else {}
    worst = min(all_trades, key=lambda t: t["pnl_usd"]) if all_trades else {}

    # ── Per-ticker stats ──────────────────────────────────────────
    ticker_stats = {}
    for ticker, trades in by_ticker.items():
        t_wins = sum(1 for t in trades if t["pnl_usd"] > 0)
        t_pnl  = sum(t["pnl_usd"] for t in trades)
        ticker_stats[ticker] = {
            "trades":    len(trades),
            "win_rate":  t_wins / len(trades) if trades else 0,
            "avg_pnl":   t_pnl / len(trades) if trades else 0,
            "total_pnl": t_pnl,
        }

    # ── Per-direction stats ───────────────────────────────────────
    direction_stats = {}
    for direction, trades in by_direction.items():
        d_wins = sum(1 for t in trades if t["pnl_usd"] > 0)
        d_pnl  = sum(t["pnl_usd"] for t in trades)
        direction_stats[direction] = {
            "trades":   len(trades),
            "win_rate": d_wins / len(trades) if trades else 0,
            "avg_pnl":  d_pnl / len(trades) if trades else 0,
        }

    # ── Per-confidence-band stats ─────────────────────────────────
    conf_stats = {}
    for band, trades in sorted(by_conf_band.items()):
        b_wins = sum(1 for t in trades if t["pnl_usd"] > 0)
        conf_stats[band] = {
            "trades":   len(trades),
            "win_rate": b_wins / len(trades) if trades else 0,
        }

    # ── Extract patterns (human-readable) ─────────────────────────
    patterns = _extract_patterns(
        win_rate, ticker_stats, direction_stats, conf_stats, best, worst, n
    )

    # ── Build prompt context ──────────────────────────────────────
    prompt_context = _build_prompt_context(
        n, win_rate, total_pnl, avg_pnl, ticker_stats, direction_stats,
        conf_stats, patterns
    )

    report = {
        "total_trades":      n,
        "win_rate":          round(win_rate, 3),
        "total_pnl_usd":    round(total_pnl, 2),
        "avg_pnl_usd":      round(avg_pnl, 2),
        "best_trade":        best,
        "worst_trade":       worst,
        "by_ticker":         ticker_stats,
        "by_direction":      direction_stats,
        "by_confidence_band": conf_stats,
        "patterns":          patterns,
        "prompt_context":    prompt_context,
        "analyzed_at":       datetime.now(timezone.utc).isoformat(),
    }

    # Persist
    LESSONS_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def get_prompt_context() -> str:
    """
    Returns the prompt_context string from the last analysis.
    If no analysis exists or file is missing, returns empty string.
    Safe to call from agent prompts.
    """
    if not LESSONS_FILE.exists():
        return ""
    try:
        data = json.loads(LESSONS_FILE.read_text(encoding="utf-8"))
        return data.get("prompt_context", "")
    except Exception:
        return ""


# ------------------------------------------------------------------
# Pattern extraction
# ------------------------------------------------------------------

def _extract_patterns(
    win_rate: float,
    ticker_stats: dict,
    direction_stats: dict,
    conf_stats: dict,
    best: dict,
    worst: dict,
    total: int,
) -> list[str]:
    """Generates human-readable patterns from stats."""
    patterns = []

    if total < 3:
        patterns.append(f"Only {total} trades completed — insufficient data for patterns.")
        return patterns

    # Overall performance
    if win_rate >= 0.60:
        patterns.append(f"Strong overall win rate: {win_rate:.0%} ({total} trades)")
    elif win_rate <= 0.40:
        patterns.append(f"Low win rate: {win_rate:.0%} — consider raising MIN_CONFIDENCE")

    # Best/worst ticker
    if ticker_stats:
        best_ticker = max(ticker_stats, key=lambda t: ticker_stats[t]["total_pnl"])
        worst_ticker = min(ticker_stats, key=lambda t: ticker_stats[t]["total_pnl"])
        bt = ticker_stats[best_ticker]
        wt = ticker_stats[worst_ticker]
        if bt["total_pnl"] > 0:
            patterns.append(
                f"Best performer: {best_ticker} — "
                f"WR {bt['win_rate']:.0%}, avg ${bt['avg_pnl']:+.2f} ({bt['trades']} trades)"
            )
        if wt["total_pnl"] < 0:
            patterns.append(
                f"Worst performer: {worst_ticker} — "
                f"WR {wt['win_rate']:.0%}, avg ${wt['avg_pnl']:+.2f} ({wt['trades']} trades)"
            )

    # Direction bias
    for d, stats in direction_stats.items():
        if stats["trades"] >= 3 and stats["win_rate"] >= 0.65:
            patterns.append(f"{d} trades outperform: WR {stats['win_rate']:.0%}")
        elif stats["trades"] >= 3 and stats["win_rate"] <= 0.35:
            patterns.append(f"{d} trades underperform: WR {stats['win_rate']:.0%} — reduce {d} bias")

    # Confidence calibration
    for band, stats in sorted(conf_stats.items()):
        if stats["trades"] >= 3:
            if stats["win_rate"] >= 0.70:
                patterns.append(f"Confidence {band}: WR {stats['win_rate']:.0%} — well calibrated")
            elif stats["win_rate"] <= 0.30:
                patterns.append(
                    f"Confidence {band}: WR {stats['win_rate']:.0%} — "
                    f"overconfident at this level, raise threshold"
                )

    # Exit reasons
    if best and best.get("exit_reason") == "TP":
        patterns.append(f"Best trade hit TP: {best['ticker']} ${best['pnl_usd']:+.2f}")
    if worst and worst.get("exit_reason") == "SL":
        patterns.append(f"Worst trade hit SL: {worst['ticker']} ${worst['pnl_usd']:+.2f}")

    return patterns


# ------------------------------------------------------------------
# Prompt context builder
# ------------------------------------------------------------------

def _build_prompt_context(
    total: int,
    win_rate: float,
    total_pnl: float,
    avg_pnl: float,
    ticker_stats: dict,
    direction_stats: dict,
    conf_stats: dict,
    patterns: list[str],
) -> str:
    """Builds a concise text block suitable for injection into agent prompts."""
    if total == 0:
        return ""

    lines = [
        f"Historical performance ({total} closed trades):",
        f"  Win rate: {win_rate:.0%} | Total PnL: ${total_pnl:+,.2f} | Avg: ${avg_pnl:+,.2f}/trade",
    ]

    # Per-ticker summary
    if ticker_stats:
        tk_parts = []
        for ticker, s in sorted(ticker_stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
            tk_parts.append(f"{ticker} WR={s['win_rate']:.0%} PnL=${s['total_pnl']:+.0f}")
        lines.append(f"  By ticker: {' | '.join(tk_parts)}")

    # Per-direction summary
    if direction_stats:
        d_parts = []
        for d, s in direction_stats.items():
            d_parts.append(f"{d} WR={s['win_rate']:.0%} ({s['trades']})")
        lines.append(f"  By direction: {' | '.join(d_parts)}")

    # Patterns
    if patterns:
        lines.append("  Lessons learned:")
        for p in patterns[:5]:  # max 5 most relevant
            lines.append(f"    - {p}")

    return "\n".join(lines)


def _empty_report() -> dict:
    return {
        "total_trades":       0,
        "win_rate":           0.0,
        "total_pnl_usd":     0.0,
        "avg_pnl_usd":       0.0,
        "best_trade":        {},
        "worst_trade":       {},
        "by_ticker":         {},
        "by_direction":      {},
        "by_confidence_band": {},
        "patterns":          ["No closed trades yet — learning starts after first position closes."],
        "prompt_context":    "",
        "analyzed_at":       datetime.now(timezone.utc).isoformat(),
    }
