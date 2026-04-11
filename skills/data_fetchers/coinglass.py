"""
Skill: data_fetchers/coinglass
Derivatives market data via Binance Futures public API.

Replaced CoinGlass (went paid-only, returns 0s silently) with Binance Futures
endpoints — free, reliable, no auth required.

Endpoints used:
  - /fapi/v1/premiumIndex     → current funding rate (real-time)
  - /futures/data/globalLongShortAccountRatio → long/short ratio

Why it matters for trading signals:
  - Funding Rate > 0.1%  → longs paying shorts → overheated longs → potential reversal
  - Funding Rate < -0.1% → shorts paying longs → overheated shorts → potential squeeze
  - Long/Short ratio > 65% longs → crowded longs → contrarian bearish
  - Long/Short ratio < 35% longs → crowded shorts → contrarian bullish
"""

import requests
from datetime import datetime, timezone

BINANCE_FAPI = "https://fapi.binance.com"

# Ticker → Binance USDT-M perp symbol
SYMBOL_MAP = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "SOL":  "SOLUSDT",
    "BNB":  "BNBUSDT",
    "XRP":  "XRPUSDT",
    "AVAX": "AVAXUSDT",
    "DOGE": "DOGEUSDT",
    "ARB":  "ARBUSDT",
}


def fetch_funding_rates(tickers: list[str]) -> list[dict]:
    """
    Fetches current funding rates from Binance Futures (premiumIndex).

    Returns:
        [{"ticker", "avg_funding_rate_pct", "signal", "interpretation"}, ...]
    """
    results = []
    for ticker in tickers:
        symbol = SYMBOL_MAP.get(ticker, f"{ticker}USDT")
        try:
            resp = requests.get(
                f"{BINANCE_FAPI}/fapi/v1/premiumIndex",
                params={"symbol": symbol},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            rate = float(data.get("lastFundingRate", 0))
            signal, interpretation = _interpret_funding(rate)

            results.append({
                "ticker":               ticker,
                "avg_funding_rate_pct": round(rate * 100, 4),
                "signal":               round(signal, 3),
                "interpretation":       interpretation,
            })

        except Exception as e:
            results.append({**_neutral_funding(ticker), "error": str(e)})

    return results


def fetch_long_short_ratio(tickers: list[str]) -> list[dict]:
    """
    Fetches global long/short account ratio from Binance Futures.

    Returns:
        [{"ticker", "long_pct", "short_pct", "signal", "interpretation"}, ...]
    """
    results = []
    for ticker in tickers:
        symbol = SYMBOL_MAP.get(ticker, f"{ticker}USDT")
        try:
            resp = requests.get(
                f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio",
                params={"symbol": symbol, "period": "1h", "limit": 1},
                timeout=10,
            )
            resp.raise_for_status()
            entries = resp.json()

            if not entries:
                results.append(_neutral_ls(ticker))
                continue

            entry    = entries[0]
            long_pct = float(entry.get("longAccount", 0.5))
            short_pct = 1.0 - long_pct
            signal   = round((0.5 - long_pct) * 2, 3)  # contrarian mapping

            results.append({
                "ticker":         ticker,
                "long_pct":       round(long_pct * 100, 1),
                "short_pct":      round(short_pct * 100, 1),
                "signal":         signal,
                "interpretation": _interpret_ls(long_pct),
            })

        except Exception as e:
            results.append({**_neutral_ls(ticker), "error": str(e)})

    return results


def fetch_derivatives_snapshot(tickers: list[str]) -> dict:
    """
    Full derivatives snapshot for the InvestigatorAgent.
    """
    return {
        "funding_rates":      fetch_funding_rates(tickers),
        "long_short_ratios":  fetch_long_short_ratio(tickers),
        "fetched_at":         datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _interpret_funding(rate: float) -> tuple[float, str]:
    """Maps funding rate to signal and interpretation string."""
    rate_pct = rate * 100
    if rate_pct > 0.1:
        return -0.5, "Longs overheated — potential reversal"
    elif rate_pct > 0.05:
        return -0.2, "Slightly bullish — mild long bias"
    elif rate_pct < -0.1:
        return 0.5, "Shorts overheated — potential squeeze"
    elif rate_pct < -0.05:
        return 0.2, "Slightly bearish — mild short bias"
    else:
        return 0.0, "Neutral funding"


def _interpret_ls(long_pct: float) -> str:
    if long_pct > 0.65:
        return "Crowded longs — contrarian bearish"
    elif long_pct > 0.55:
        return "Mild long bias"
    elif long_pct < 0.35:
        return "Crowded shorts — contrarian bullish"
    elif long_pct < 0.45:
        return "Mild short bias"
    return "Balanced"


def _neutral_funding(ticker: str) -> dict:
    return {
        "ticker":               ticker,
        "avg_funding_rate_pct": 0.0,
        "signal":               0.0,
        "interpretation":       "No data",
    }


def _neutral_ls(ticker: str) -> dict:
    return {
        "ticker":         ticker,
        "long_pct":       50.0,
        "short_pct":      50.0,
        "signal":         0.0,
        "interpretation": "No data",
    }
