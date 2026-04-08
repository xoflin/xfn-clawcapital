"""
Skill: data_fetchers/rss_feeds
Aggregator for crypto news RSS feeds.

Curated feeds:
  - Cointelegraph (market news)
  - CoinDesk (industry reporting)
  - Bitcoin Magazine (Bitcoin-focused)
  - The Block (research & analysis)
  - Crypto Briefing (market alerts)

Each cycle fetches ~5-10 newest articles per feed.
Dependency: pip install feedparser

Output: list of articles with title, link, published_at, source
"""

import feedparser
import time
from datetime import datetime, timezone
from typing import Literal


# Curated RSS feeds for crypto market intelligence
DEFAULT_FEEDS: dict[str, str] = {
    "cointelegraph": "https://cointelegraph.com/feed",
    "coindesk": "https://feeds.coindesk.com/news",
    "bitcoin_magazine": "https://bitcoinmagazine.com/feed",
    "the_block": "https://www.theblockcrypto.com/feed",
    "crypto_briefing": "https://feeds.cryptobriefing.com/latest",
}


def fetch_rss_feeds(
    feed_urls: dict[str, str] | None = None,
    max_per_feed: int = 10,
    timeout: int = 30,
) -> dict:
    """
    Fetches and aggregates articles from multiple RSS feeds.

    Args:
        feed_urls:  Dict of {name: url}. Defaults to DEFAULT_FEEDS.
        max_per_feed: Maximum articles per feed.
        timeout:    Request timeout per feed (seconds).

    Returns:
        {
            "articles": [
                {
                    "source": str,
                    "title": str,
                    "link": str,
                    "published_at": str (ISO),
                    "summary": str,
                },
                ...
            ],
            "feed_status": {
                "cointelegraph": {"status": "ok" | "error", "article_count": int},
                ...
            }
        }
    """
    if feed_urls is None:
        feed_urls = DEFAULT_FEEDS

    articles = []
    feed_status = {}

    for feed_name, feed_url in feed_urls.items():
        try:
            feed = feedparser.parse(feed_url, timeout=timeout)

            if feed.status >= 400:
                feed_status[feed_name] = {
                    "status": "error",
                    "article_count": 0,
                    "error": f"HTTP {feed.status}",
                }
                continue

            entries = feed.get("entries", [])[:max_per_feed]

            for entry in entries:
                articles.append(
                    {
                        "source": feed_name,
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "published_at": _parse_timestamp(entry),
                        "summary": entry.get("summary", "")[:500],  # Truncate
                    }
                )

            feed_status[feed_name] = {
                "status": "ok",
                "article_count": len(entries),
            }

        except Exception as e:
            feed_status[feed_name] = {
                "status": "error",
                "article_count": 0,
                "error": str(e),
            }

    # Sort by published_at (most recent first)
    articles.sort(
        key=lambda x: _to_timestamp(x["published_at"]),
        reverse=True,
    )

    return {
        "articles": articles,
        "feed_status": feed_status,
        "total_articles": len(articles),
    }


def _parse_timestamp(entry: dict) -> str:
    """
    Extracts and normalizes published timestamp from RSS entry.

    Args:
        entry: feedparser entry dict.

    Returns:
        ISO 8601 timestamp string (UTC).
    """
    # Try common RSS fields
    for field in ["published_parsed", "updated_parsed", "created_parsed"]:
        if field in entry and entry[field]:
            try:
                dt = datetime(*entry[field][:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (ValueError, TypeError):
                continue

    # Fallback to now
    return datetime.now(timezone.utc).isoformat()


def _to_timestamp(iso_str: str) -> float:
    """Converts ISO string to Unix timestamp for sorting."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return time.time()


def add_custom_feed(feed_dict: dict, name: str, url: str) -> None:
    """
    Adds a custom feed to the defaults.

    Args:
        feed_dict: Feeds dict to update.
        name:      Feed identifier.
        url:       RSS feed URL.
    """
    feed_dict[name] = url


def filter_articles_by_keywords(
    articles: list[dict],
    keywords: list[str],
) -> list[dict]:
    """
    Filters articles by keyword search in title/summary.

    Args:
        articles:  List of article dicts.
        keywords:  Keywords to search (case-insensitive).

    Returns:
        Filtered articles.
    """
    keywords_lower = [k.lower() for k in keywords]
    result = []

    for article in articles:
        text = (
            article.get("title", "") + " " + article.get("summary", "")
        ).lower()
        if any(kw in text for kw in keywords_lower):
            result.append(article)

    return result
