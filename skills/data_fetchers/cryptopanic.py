"""
Skill: data_fetchers/cryptopanic
Connector for the CryptoPanic API — fetches raw crypto news headlines.

Input:  auth_token (str), currencies (list[str] | None), max_results (int)
Output: list[dict] with fields title, published_at, currencies, bullish_votes,
        bearish_votes, source
"""

import re
import requests
from datetime import datetime, timezone

CRYPTOPANIC_API_URL = "https://cryptopanic.com/api/v1/posts/"
DEFAULT_MAX = 20


def fetch_headlines(
    auth_token: str,
    currencies: list[str] | None = None,
    max_results: int = DEFAULT_MAX,
) -> list[dict]:
    """
    Fetches the latest news from the CryptoPanic API.

    Args:
        auth_token:  CryptoPanic authentication token.
        currencies:  Filter by tickers (e.g. ["BTC", "ETH"]).
        max_results: Maximum number of headlines to return.

    Returns:
        List of cleaned headline dicts.
    """
    params: dict = {
        "auth_token": auth_token,
        "kind": "news",
        "public": "true",
    }
    if currencies:
        params["currencies"] = ",".join(currencies)

    response = requests.get(CRYPTOPANIC_API_URL, params=params, timeout=10)
    response.raise_for_status()

    raw_results = response.json().get("results", [])[:max_results]
    return [_clean_item(item) for item in raw_results if item.get("title")]


def _clean_text(text: str) -> str:
    text = re.sub(r"[^\w\s.,!?%$€£\-/:]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_item(item: dict) -> dict:
    votes = item.get("votes", {}) or {}
    return {
        "title":         _clean_text(item.get("title", "")),
        "published_at":  item.get("published_at", ""),
        "currencies":    [c["code"] for c in item.get("currencies", [])],
        "bullish_votes": votes.get("liked", 0) or 0,
        "bearish_votes": votes.get("disliked", 0) or 0,
        "source":        item.get("source", {}).get("title", ""),
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
    }
