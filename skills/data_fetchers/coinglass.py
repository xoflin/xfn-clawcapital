"""
Skill: data_fetchers/coinglass
Connector for CoinGlass public endpoints — derivatives market data.

Public endpoints (no auth required):
  - Funding rates per asset
  - Open Interest (total $ at risk in perpetuals)
  - Long/Short ratio

Why it matters for trading signals:
  - Funding Rate > 0.1%  → longs paying shorts → overheated longs → potential reversal
  - Funding Rate < -0.1% → shorts paying longs → overheated shorts → potential squeeze
  - Rising OI + rising price → trend confirmation
  - Falling OI + rising price → weak rally, potential reversal
  - Long/Short ratio > 60% longs → crowded longs → caution

Docs: https://coinglass.com/api
"""

import requests
from datetime import datetime, timezone

COINGLASS_BASE = "https://open-api.coinglass.com/public/v2"
COINGLASS_FUTURES = "https://fapi.coinglass.com/api"

# Ticker mapping to CoinGlass symbols
TICKER_MAP = {
    "BTC": "BTC",
    "ETH": "ETH",
    "SOL": "SOL",
    "BNB": "BNB",
    "XRP": "XRP",
    "AVAX": "AVAX",
    "DOGE": "DOGE",
    "ARB": "ARB",
}


def fetch_funding_rates(tickers: list[str]) -> list[dict]:
    """
    Fetches funding rates for perpetual contracts across exchanges.

    Args:
        tickers: List of tickers (e.g. ["BTC", "ETH"]).

    Returns:
        [
            {
                "ticker": str,
                "avg_funding_rate": float (%),
                "signal": float (-1 to +1),
                "interpretation": str,
            },
            ...
        ]
    """
    results = []

    for ticker in tickers:
        symbol = TICKER_MAP.get(ticker, ticker)
        try:
            response = requests.get(
                f"{COINGLASS_FUTURES}/fundingRate/v3/history",
                params={"symbol": symbol, "interval": "8h", "limit": 3},
                headers={"accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            rates = data.get("data", {}).get("dataMap", {})
            if not rates:
                results.append(_neutral_funding(ticker))
                continue

            # Average across exchanges
            all_rates = []
            for exchange_data in rates.values():
                for entry in exchange_data[:1]:  # Latest only
                    try:
                        all_rates.append(float(entry.get("fundingRate", 0)))
                    except (ValueError, TypeError):
                        pass

            avg_rate = sum(all_rates) / len(all_rates) if all_rates else 0.0
            signal, interpretation = _interpret_funding(avg_rate)

            results.append(
                {
                    "ticker": ticker,
                    "avg_funding_rate_pct": round(avg_rate * 100, 4),
                    "signal": round(signal, 3),
                    "interpretation": interpretation,
                }
            )

        except Exception as e:
            results.append({**_neutral_funding(ticker), "error": str(e)})

    return results


def fetch_long_short_ratio(tickers: list[str]) -> list[dict]:
    """
    Fetches long/short ratio for major assets.

    Args:
        tickers: List of tickers.

    Returns:
        [{"ticker": str, "long_pct": float, "short_pct": float, "signal": float}, ...]
    """
    results = []

    for ticker in tickers:
        symbol = TICKER_MAP.get(ticker, ticker)
        try:
            response = requests.get(
                f"https://fapi.coinglass.com/api/longShortRate",
                params={"symbol": symbol, "interval": "1h", "limit": 1},
                headers={"accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            entries = data.get("data", {})
            if not entries:
                results.append(_neutral_ls(ticker))
                continue

            # Get latest entry across exchanges
            long_rates = []
            for exchange_data in entries.values():
                if exchange_data:
                    try:
                        long_rates.append(float(exchange_data[0].get("longRatio", 0.5)))
                    except (ValueError, TypeError):
                        pass

            avg_long = sum(long_rates) / len(long_rates) if long_rates else 0.5
            avg_short = 1.0 - avg_long

            # Signal: 0.5 long → 0 (neutral), 0.7 long → -0.4 (crowded longs = bearish)
            # Contrarian: too many longs = potential dump, too many shorts = potential squeeze
            signal = round((0.5 - avg_long) * 2, 3)  # Contrarian mapping

            results.append(
                {
                    "ticker": ticker,
                    "long_pct": round(avg_long * 100, 1),
                    "short_pct": round(avg_short * 100, 1),
                    "signal": signal,
                    "interpretation": _interpret_ls(avg_long),
                }
            )

        except Exception as e:
            results.append({**_neutral_ls(ticker), "error": str(e)})

    return results


def fetch_derivatives_snapshot(tickers: list[str]) -> dict:
    """
    Full derivatives snapshot for the InvestigatorAgent.

    Returns:
        {
            "funding_rates": [...],
            "long_short_ratios": [...],
            "fetched_at": str,
        }
    """
    return {
        "funding_rates": fetch_funding_rates(tickers),
        "long_short_ratios": fetch_long_short_ratio(tickers),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _interpret_funding(rate: float) -> tuple[float, str]:
    """Maps funding rate to signal and interpretation."""
    rate_pct = rate * 100
    if rate_pct > 0.1:
        return -0.5, "Longs overheated — potential reversal"
    elif rate_pct > 0.05:
        return -0.2, "Mildly positive — slight long bias"
    elif rate_pct < -0.1:
        return 0.5, "Shorts overheated — potential squeeze"
    elif rate_pct < -0.05:
        return 0.2, "Mildly negative — slight short bias"
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
        "ticker": ticker,
        "avg_funding_rate_pct": 0.0,
        "signal": 0.0,
        "interpretation": "No data",
    }


def _neutral_ls(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "long_pct": 50.0,
        "short_pct": 50.0,
        "signal": 0.0,
        "interpretation": "No data",
    }
