"""
Skill: data_fetchers/cryptocompare_news
Fetches crypto news from CryptoCompare News API.

100% free — no API key required.
Endpoint: https://min-api.cryptocompare.com/data/v2/news/

Output: list of articles with title, source, published_at, sentiment votes
"""

import requests
from datetime import datetime, timezone

CRYPTOCOMPARE_URL = "https://min-api.cryptocompare.com/data/v2/news/"
DEFAULT_MAX = 20

# Map tickers to CryptoCompare categories
TICKER_CATEGORIES: dict[str, str] = {
    "BTC": "BTC",
    "ETH": "ETH",
    "SOL": "SOL",
    "ARB": "ARB",
    "MATIC": "MATIC",
    "AVAX": "AVAX",
    "BNB": "BNB",
    "OP": "OP",
}


def fetch_news(
    tickers: list[str] | None = None,
    max_results: int = DEFAULT_MAX,
    timeout: int = 10,
) -> list[dict]:
    """
    Fetches latest crypto news from CryptoCompare.

    Args:
        tickers:     Filter by tickers (e.g. ["BTC", "ETH"]).
                     If None, fetches general crypto news.
        max_results: Maximum number of articles to return.
        timeout:     Request timeout in seconds.

    Returns:
        List of articles:
        [
            {
                "title": str,
                "source": str,
                "url": str,
                "published_at": str (ISO),
                "body": str (truncated to 300 chars),
                "categories": str,
            },
            ...
        ]
    """
    # Fetch general news (no category filter — more reliable than the categories param,
    # which can return a dict instead of a list and cause slicing errors).
    # Ticker filtering is done client-side after fetching.
    params: dict = {"lang": "EN", "sortOrder": "latest"}

    try:
        resp = requests.get(CRYPTOCOMPARE_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"CryptoCompare News fetch failed: {e}")

    raw_data = data.get("Data")
    if not isinstance(raw_data, list):
        msg = data.get("Message", "unexpected API response format")
        raise RuntimeError(f"CryptoCompare News: {msg}")

    ticker_set = {t.upper() for t in tickers} if tickers else set()

    articles = []
    for item in raw_data:
        # Client-side ticker filter: include article if it mentions any watchlist ticker
        if ticker_set:
            cats = (item.get("categories", "") or "").upper()
            tags = (item.get("tags", "") or "").upper()
            title = (item.get("title", "") or "").upper()
            combined = f"{cats} {tags} {title}"
            if not any(t in combined for t in ticker_set):
                continue

        published_ts = item.get("published_on", 0)
        published_at = (
            datetime.fromtimestamp(published_ts, tz=timezone.utc).isoformat()
            if published_ts else datetime.now(timezone.utc).isoformat()
        )
        articles.append({
            "title":        item.get("title", ""),
            "source":       item.get("source", ""),
            "url":          item.get("url", ""),
            "published_at": published_at,
            "body":         item.get("body", "")[:300],
            "categories":   item.get("categories", ""),
        })

        if len(articles) >= max_results:
            break

    return articles


def format_for_prompt(articles: list[dict], max_items: int = 15) -> str:
    """Formats articles into a string for the Gemini prompt."""
    if not articles:
        return "No news available."
    lines = []
    for a in articles[:max_items]:
        date = a.get("published_at", "")[:10]
        title = a.get("title", "")
        source = a.get("source", "")
        lines.append(f"  [{date}] [{source}] {title}")
    return "\n".join(lines)
