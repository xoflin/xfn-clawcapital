"""
Skill: data_fetchers/coinglass
Derivatives market data — funding rates and long/short ratios.

Sources tried in order (first success wins):
  1. Bybit   — global, no auth, reliable
  2. Binance  — blocked in some EU regions
  3. OKX      — fallback

Why it matters for trading signals:
  - Funding Rate > 0.1%  → longs overheated → potential reversal
  - Funding Rate < -0.1% → shorts overheated → potential squeeze
  - Long > 65%           → crowded longs → contrarian bearish
  - Long < 35%           → crowded shorts → contrarian bullish
"""

import requests
from datetime import datetime, timezone

_TIMEOUT = 10

# Ticker → exchange symbol mappings
_BYBIT_MAP  = {t: f"{t}USDT" for t in ("BTC", "ETH", "SOL", "BNB", "XRP", "AVAX", "DOGE", "ARB")}
_BINANCE_MAP = _BYBIT_MAP.copy()
_OKX_MAP    = {t: f"{t}-USDT-SWAP" for t in ("BTC", "ETH", "SOL", "BNB", "XRP", "AVAX", "DOGE", "ARB")}


# ------------------------------------------------------------------
# Funding rate — per-source fetchers
# ------------------------------------------------------------------

def _funding_bybit(symbol: str) -> float:
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "linear", "symbol": symbol},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    items = r.json().get("result", {}).get("list", [])
    if not items:
        raise ValueError("empty list")
    return float(items[0]["fundingRate"])


def _funding_binance(symbol: str) -> float:
    r = requests.get(
        "https://fapi.binance.com/fapi/v1/premiumIndex",
        params={"symbol": symbol},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return float(r.json()["lastFundingRate"])


def _funding_okx(symbol: str) -> float:
    r = requests.get(
        "https://www.okx.com/api/v5/public/funding-rate",
        params={"instId": symbol},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        raise ValueError("empty data")
    return float(data[0]["fundingRate"])


# ------------------------------------------------------------------
# Long/Short ratio — per-source fetchers
# ------------------------------------------------------------------

def _ls_bybit(symbol: str) -> float:
    """Returns long ratio (0-1)."""
    r = requests.get(
        "https://api.bybit.com/v5/market/account-ratio",
        params={"category": "linear", "symbol": symbol, "period": "1h", "limit": 1},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    items = r.json().get("result", {}).get("list", [])
    if not items:
        raise ValueError("empty list")
    return float(items[0]["buyRatio"])


def _ls_binance(symbol: str) -> float:
    """Returns long ratio (0-1)."""
    r = requests.get(
        "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
        params={"symbol": symbol, "period": "1h", "limit": 1},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    entries = r.json()
    if not entries:
        raise ValueError("empty response")
    return float(entries[0]["longAccount"])


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def fetch_funding_rates(tickers: list) -> list:
    """
    Fetches current perpetual funding rates.
    Tries Bybit → Binance → OKX in order.

    Returns:
        [{"ticker", "avg_funding_rate_pct", "signal", "interpretation"}, ...]
    """
    results = []
    for ticker in tickers:
        rate = None
        last_err = ""

        for fetcher, symbol_map in (
            (_funding_bybit,   _BYBIT_MAP),
            (_funding_binance, _BINANCE_MAP),
            (_funding_okx,     _OKX_MAP),
        ):
            symbol = symbol_map.get(ticker)
            if not symbol:
                continue
            try:
                rate = fetcher(symbol)
                break
            except Exception as e:
                last_err = str(e)[:60]

        if rate is None:
            results.append({**_neutral_funding(ticker), "error": last_err})
            continue

        signal, interpretation = _interpret_funding(rate)
        results.append({
            "ticker":               ticker,
            "avg_funding_rate_pct": round(rate * 100, 4),
            "signal":               round(signal, 3),
            "interpretation":       interpretation,
        })

    return results


def fetch_long_short_ratio(tickers: list) -> list:
    """
    Fetches global long/short account ratio.
    Tries Bybit → Binance in order.

    Returns:
        [{"ticker", "long_pct", "short_pct", "signal", "interpretation"}, ...]
    """
    results = []
    for ticker in tickers:
        long_ratio = None
        last_err   = ""

        for fetcher, symbol_map in (
            (_ls_bybit,   _BYBIT_MAP),
            (_ls_binance, _BINANCE_MAP),
        ):
            symbol = symbol_map.get(ticker)
            if not symbol:
                continue
            try:
                long_ratio = fetcher(symbol)
                break
            except Exception as e:
                last_err = str(e)[:60]

        if long_ratio is None:
            results.append({**_neutral_ls(ticker), "error": last_err})
            continue

        short_ratio = 1.0 - long_ratio
        signal      = round((0.5 - long_ratio) * 2, 3)  # contrarian
        results.append({
            "ticker":         ticker,
            "long_pct":       round(long_ratio * 100, 1),
            "short_pct":      round(short_ratio * 100, 1),
            "signal":         signal,
            "interpretation": _interpret_ls(long_ratio),
        })

    return results


def fetch_derivatives_snapshot(tickers: list) -> dict:
    return {
        "funding_rates":     fetch_funding_rates(tickers),
        "long_short_ratios": fetch_long_short_ratio(tickers),
        "fetched_at":        datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _interpret_funding(rate: float) -> tuple:
    pct = rate * 100
    if pct > 0.1:   return -0.5, "Longs overheated — potential reversal"
    if pct > 0.05:  return -0.2, "Slightly bullish — mild long bias"
    if pct < -0.1:  return  0.5, "Shorts overheated — potential squeeze"
    if pct < -0.05: return  0.2, "Slightly bearish — mild short bias"
    return 0.0, "Neutral funding"


def _interpret_ls(long_pct: float) -> str:
    if long_pct > 0.65: return "Crowded longs — contrarian bearish"
    if long_pct > 0.55: return "Mild long bias"
    if long_pct < 0.35: return "Crowded shorts — contrarian bullish"
    if long_pct < 0.45: return "Mild short bias"
    return "Balanced"


def _neutral_funding(ticker: str) -> dict:
    return {"ticker": ticker, "avg_funding_rate_pct": 0.0, "signal": 0.0, "interpretation": "No data"}


def _neutral_ls(ticker: str) -> dict:
    return {"ticker": ticker, "long_pct": 50.0, "short_pct": 50.0, "signal": 0.0, "interpretation": "No data"}
