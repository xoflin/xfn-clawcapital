"""
Skill: data_fetchers/coingecko
Connector for the CoinGecko API — real-time prices, OHLC and market data.

Input:  api_key (str | None), vs_currency (str)
Output: snapshots, OHLC candles
"""

import time
import requests
from datetime import datetime, timezone

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# Mapping of common tickers to CoinGecko IDs
TICKER_TO_ID: dict[str, str] = {
    "BTC":   "bitcoin",
    "ETH":   "ethereum",
    "SOL":   "solana",
    "BNB":   "binancecoin",
    "XRP":   "ripple",
    "ADA":   "cardano",
    "DOGE":  "dogecoin",
    "AVAX":  "avalanche-2",
    "DOT":   "polkadot",
    "MATIC": "matic-network",
    "LINK":  "chainlink",
    "LTC":   "litecoin",
    "UNI":   "uniswap",
    "ATOM":  "cosmos",
    "XLM":   "stellar",
}


class CoinGeckoClient:
    """
    HTTP client for the CoinGecko API (public or Pro).

    Args:
        api_key:     CoinGecko Pro key (optional). Without a key uses the
                     public endpoint (~30 req/min limit).
        vs_currency: Reference currency (default: "usd").
    """

    def __init__(self, api_key: str | None = None, vs_currency: str = "usd"):
        self.vs_currency = vs_currency.lower()
        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json"})
        if api_key:
            self.session.headers.update({"x-cg-demo-api-key": api_key})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def resolve_id(self, ticker: str) -> str:
        """Converts a ticker (e.g. BTC) to a CoinGecko ID (e.g. bitcoin)."""
        cg_id = TICKER_TO_ID.get(ticker.upper())
        if not cg_id:
            raise ValueError(
                f"Ticker '{ticker}' not mapped. "
                f"Add it to TICKER_TO_ID or use the CoinGecko ID directly."
            )
        return cg_id

    def get(self, endpoint: str, params: dict) -> dict | list:
        url = f"{COINGECKO_BASE_URL}{endpoint}"
        response = self.session.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def ping(self) -> bool:
        """Checks API connectivity."""
        try:
            self.get("/ping", {})
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def get_snapshot(self, ticker: str) -> dict:
        """
        Returns the current snapshot for an asset:
        price, 24h change, volume, market cap, ATH.
        """
        cg_id = self.resolve_id(ticker)
        data = self.get("/coins/markets", params={
            "vs_currency": self.vs_currency,
            "ids": cg_id,
            "price_change_percentage": "24h",
        })
        if not data:
            raise ValueError(f"No data for '{ticker}' ({cg_id}).")
        item = data[0]
        return {
            "ticker":          ticker.upper(),
            "coingecko_id":    cg_id,
            "currency":        self.vs_currency,
            "price":           item["current_price"],
            "change_24h_pct":  round(item["price_change_percentage_24h"] or 0, 4),
            "volume_24h":      item["total_volume"],
            "market_cap":      item["market_cap"],
            "ath":             item["ath"],
            "ath_change_pct":  round(item["ath_change_percentage"] or 0, 4),
            "last_updated":    item["last_updated"],
            "fetched_at":      datetime.now(timezone.utc).isoformat(),
        }

    def get_batch_snapshots(self, tickers: list[str]) -> list[dict]:
        """
        Fetches snapshots for multiple assets in a single API call.
        More efficient than calling get_snapshot() individually.
        """
        ids = [self.resolve_id(t) for t in tickers]
        data = self.get("/coins/markets", params={
            "vs_currency": self.vs_currency,
            "ids": ",".join(ids),
            "price_change_percentage": "24h",
        })
        id_to_ticker = {self.resolve_id(t): t.upper() for t in tickers}
        return [
            {
                "ticker":         id_to_ticker.get(item["id"], item["id"]),
                "price":          item["current_price"],
                "change_24h_pct": round(item["price_change_percentage_24h"] or 0, 4),
                "volume_24h":     item["total_volume"],
                "market_cap":     item["market_cap"],
                "fetched_at":     datetime.now(timezone.utc).isoformat(),
            }
            for item in data
        ]

    # ------------------------------------------------------------------
    # OHLC
    # ------------------------------------------------------------------

    def get_ohlc(self, ticker: str, days: int = 30) -> list[dict]:
        """
        Returns OHLC data for the last N days.
        CoinGecko returns 30-min intervals (≤2 days), 4h (≤30 days),
        daily (>30 days).
        """
        cg_id = self.resolve_id(ticker)
        raw = self.get(f"/coins/{cg_id}/ohlc", params={
            "vs_currency": self.vs_currency,
            "days": days,
        })
        return [
            {
                "timestamp": datetime.fromtimestamp(
                    row[0] / 1000, tz=timezone.utc
                ).isoformat(),
                "open":  row[1],
                "high":  row[2],
                "low":   row[3],
                "close": row[4],
            }
            for row in raw
        ]
