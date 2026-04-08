"""
Skill: data_fetchers/alpha_vantage
Connector for the Alpha Vantage API.
Provides prices, volume and technical indicators for crypto and equities.

Free plan: 25 req/day — use sparingly.
Use as secondary source / validation alongside CoinGecko.

Endpoints covered:
  - Crypto intraday (OHLCV every 5/15/30/60 min)
  - Crypto daily  (daily OHLCV)
  - RSI           (technical indicator)
  - MACD          (technical indicator)
"""

import requests
from datetime import datetime, timezone

ALPHA_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    """
    Client for the Alpha Vantage API.

    Args:
        api_key: Alpha Vantage API key (free at alphavantage.co).
        market:  Reference market for crypto (default: "USD").
    """

    def __init__(self, api_key: str, market: str = "USD"):
        self.api_key = api_key
        self.market = market.upper()
        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json"})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get(self, params: dict) -> dict:
        params["apikey"] = self.api_key
        response = self.session.get(ALPHA_BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Alpha Vantage returns errors as JSON fields, not HTTP 4xx
        if "Error Message" in data:
            raise ValueError(f"Alpha Vantage error: {data['Error Message']}")
        if "Information" in data:
            raise RuntimeError(f"Alpha Vantage rate limit: {data['Information']}")

        return data

    # ------------------------------------------------------------------
    # 1. Daily crypto price (OHLCV)
    # ------------------------------------------------------------------

    def get_crypto_daily(
        self,
        symbol: str,
        limit: int = 30,
    ) -> list[dict]:
        """
        Returns the last N days of OHLCV for a crypto pair.

        Args:
            symbol: Asset ticker (e.g. "BTC", "ETH").
            limit:  Number of days to return.

        Returns:
            List of candles [{date, open, high, low, close, volume}, ...],
            in chronological order (oldest first).
        """
        data = self._get({
            "function": "DIGITAL_CURRENCY_DAILY",
            "symbol":   symbol.upper(),
            "market":   self.market,
        })

        raw = data.get("Time Series (Digital Currency Daily)", {})
        candles = []
        for date_str, values in sorted(raw.items()):
            candles.append({
                "date":   date_str,
                "open":   float(values.get("1. open", 0)),
                "high":   float(values.get("2. high", 0)),
                "low":    float(values.get("3. low", 0)),
                "close":  float(values.get("4. close", 0)),
                "volume": float(values.get("5. volume", 0)),
            })

        return candles[-limit:]

    # ------------------------------------------------------------------
    # 2. Quick snapshot (latest daily close)
    # ------------------------------------------------------------------

    def get_snapshot(self, symbol: str) -> dict:
        """
        Returns the most recent snapshot for a crypto asset.

        Returns:
            {ticker, close, open, high, low, volume, date, fetched_at}
        """
        candles = self.get_crypto_daily(symbol, limit=1)
        if not candles:
            raise ValueError(f"No data for '{symbol}'")

        c = candles[-1]
        return {
            "ticker":     symbol.upper(),
            "source":     "alpha_vantage",
            "date":       c["date"],
            "close":      c["close"],
            "open":       c["open"],
            "high":       c["high"],
            "low":        c["low"],
            "volume":     c["volume"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # 3. RSI
    # ------------------------------------------------------------------

    def get_rsi(
        self,
        symbol: str,
        interval: str = "daily",
        time_period: int = 14,
        limit: int = 10,
    ) -> list[dict]:
        """
        Returns the most recent RSI values.

        Args:
            symbol:      Ticker (e.g. "BTC").
            interval:    Time interval ("daily", "weekly", "60min").
            time_period: RSI period (default 14).
            limit:       Number of values to return.

        Returns:
            List [{date, rsi}, ...], chronological order.
        """
        data = self._get({
            "function":    "RSI",
            "symbol":      f"{symbol.upper()}{self.market}",
            "interval":    interval,
            "time_period": time_period,
            "series_type": "close",
        })

        raw = data.get("Technical Analysis: RSI", {})
        values = [
            {"date": date, "rsi": round(float(v["RSI"]), 4)}
            for date, v in sorted(raw.items())
        ]
        return values[-limit:]

    # ------------------------------------------------------------------
    # 4. MACD
    # ------------------------------------------------------------------

    def get_macd(
        self,
        symbol: str,
        interval: str = "daily",
        limit: int = 10,
    ) -> list[dict]:
        """
        Returns the most recent MACD values.

        Args:
            symbol:   Ticker (e.g. "BTC").
            interval: Time interval ("daily", "weekly", "60min").
            limit:    Number of values to return.

        Returns:
            List [{date, macd, signal, histogram}, ...], chronological order.
        """
        data = self._get({
            "function":     "MACD",
            "symbol":       f"{symbol.upper()}{self.market}",
            "interval":     interval,
            "series_type":  "close",
            "fastperiod":   12,
            "slowperiod":   26,
            "signalperiod": 9,
        })

        raw = data.get("Technical Analysis: MACD", {})
        values = [
            {
                "date":      date,
                "macd":      round(float(v["MACD"]), 6),
                "signal":    round(float(v["MACD_Signal"]), 6),
                "histogram": round(float(v["MACD_Hist"]), 6),
            }
            for date, v in sorted(raw.items())
        ]
        return values[-limit:]

    # ------------------------------------------------------------------
    # 5. Full technical report
    # ------------------------------------------------------------------

    def get_technical_report(self, symbol: str) -> dict:
        """
        Aggregates snapshot + RSI + MACD into a single output.
        Consumes 3 requests from the daily quota.

        Returns:
            {ticker, snapshot, rsi_latest, macd_latest, signal, fetched_at}
        """
        import time

        snapshot = self.get_snapshot(symbol)
        time.sleep(1)  # Respect rate limit (5 req/min on free plan)

        rsi_values = self.get_rsi(symbol, limit=3)
        time.sleep(1)

        macd_values = self.get_macd(symbol, limit=3)

        rsi_latest  = rsi_values[-1] if rsi_values else None
        macd_latest = macd_values[-1] if macd_values else None

        signal = _derive_signal(rsi_latest, macd_latest)

        return {
            "ticker":      symbol.upper(),
            "source":      "alpha_vantage",
            "snapshot":    snapshot,
            "rsi_latest":  rsi_latest,
            "macd_latest": macd_latest,
            "signal":      signal,
            "fetched_at":  datetime.now(timezone.utc).isoformat(),
        }


# ------------------------------------------------------------------
# Signal utility
# ------------------------------------------------------------------

def _derive_signal(
    rsi: dict | None,
    macd: dict | None,
) -> dict:
    """
    Combined RSI + MACD technical signal.

    RSI:  < 30 → oversold (Bullish) | > 70 → overbought (Bearish)
    MACD: histogram > 0 → positive momentum | < 0 → negative
    """
    signals = []
    reasons = []

    if rsi:
        rsi_val = rsi["rsi"]
        if rsi_val < 30:
            signals.append(1)
            reasons.append(f"RSI oversold ({rsi_val:.1f})")
        elif rsi_val > 70:
            signals.append(-1)
            reasons.append(f"RSI overbought ({rsi_val:.1f})")
        else:
            signals.append(0)
            reasons.append(f"RSI neutral ({rsi_val:.1f})")

    if macd:
        hist = macd["histogram"]
        if hist > 0:
            signals.append(1)
            reasons.append(f"MACD positive momentum ({hist:+.4f})")
        elif hist < 0:
            signals.append(-1)
            reasons.append(f"MACD negative momentum ({hist:+.4f})")
        else:
            signals.append(0)
            reasons.append("MACD neutral")

    if not signals:
        return {"direction": "Neutral", "reason": "Insufficient data"}

    avg = sum(signals) / len(signals)
    if avg > 0.3:
        direction = "Bullish"
    elif avg < -0.3:
        direction = "Bearish"
    else:
        direction = "Neutral"

    return {"direction": direction, "reason": " | ".join(reasons)}
