"""
Skill: data_fetchers/rss_feeds
Aggregator for crypto news RSS feeds.

Curated feeds (verified working 2026-04):
  - Cointelegraph  (market news)
  - CoinDesk       (industry reporting)
  - Decrypt        (analysis + news)
  - The Block      (research)
  - Bitcoin Magazine (Bitcoin-focused)

Each cycle fetches up to max_per_feed newest articles per feed.
Articles from crypto-dedicated feeds are all relevant by definition —
keyword filtering is used only when tickers is provided.

Dependency: pip install feedparser
"""

import feedparser
import time
from datetime import datetime, timezone
from typing import Optional


# Verified RSS URLs (2026-04)
DEFAULT_FEEDS: dict[str, str] = {
    "cointelegraph":  "https://cointelegraph.com/rss",
    "decrypt":        "https://decrypt.co/feed",
    "the_block":      "https://www.theblock.co/rss.xml",
    "bitcoin_mag":    "https://bitcoinmagazine.com/.rss/full/",
    "cryptonews":     "https://cryptonews.com/news/feed/",
}


def fetch_rss_feeds(
    feed_urls: Optional[dict] = None,
    max_per_feed: int = 10,
    timeout: int = 15,
) -> dict:
    """
    Fetches and aggregates articles from multiple RSS feeds.

    Args:
        feed_urls:    Dict of {name: url}. Defaults to DEFAULT_FEEDS.
        max_per_feed: Maximum articles per feed.
        timeout:      Request timeout per feed (seconds).

    Returns:
        {
            "articles": [{"source", "title", "link", "published_at", "summary"}, ...],
            "feed_status": {"name": {"status": "ok"|"error", "article_count": int}, ...},
            "total_articles": int,
        }
    """
    if feed_urls is None:
        feed_urls = DEFAULT_FEEDS

    articles   = []
    feed_status = {}

    for feed_name, feed_url in feed_urls.items():
        try:
            feed = feedparser.parse(feed_url, request_headers={"User-Agent": "Mozilla/5.0"})

            # feedparser doesn't always populate .status (e.g. local files, bad SSL)
            status_code = getattr(feed, "status", 200)
            if status_code >= 400:
                feed_status[feed_name] = {
                    "status":        "error",
                    "article_count": 0,
                    "error":         f"HTTP {status_code}",
                }
                continue

            # bozo flag = feedparser encountered a malformed feed
            if feed.get("bozo") and not feed.get("entries"):
                exc = feed.get("bozo_exception", "malformed feed")
                feed_status[feed_name] = {
                    "status":        "error",
                    "article_count": 0,
                    "error":         str(exc)[:80],
                }
                continue

            entries = feed.get("entries", [])[:max_per_feed]

            for entry in entries:
                articles.append({
                    "source":       feed_name,
                    "title":        entry.get("title", "").strip(),
                    "link":         entry.get("link", ""),
                    "published_at": _parse_timestamp(entry),
                    "summary":      entry.get("summary", "")[:500],
                })

            feed_status[feed_name] = {
                "status":        "ok",
                "article_count": len(entries),
            }

        except Exception as e:
            feed_status[feed_name] = {
                "status":        "error",
                "article_count": 0,
                "error":         str(e)[:80],
            }

    # Sort by most recent first
    articles.sort(key=lambda x: _to_timestamp(x["published_at"]), reverse=True)

    return {
        "articles":       articles,
        "feed_status":    feed_status,
        "total_articles": len(articles),
    }


def filter_articles_by_keywords(
    articles: list[dict],
    keywords: list[str],
) -> list[dict]:
    """
    Filters articles by keyword presence in title or summary.
    Case-insensitive. Returns all articles if keywords is empty.

    Args:
        articles: List of article dicts.
        keywords: Keywords to match (case-insensitive).

    Returns:
        Filtered articles (preserves original order).
    """
    if not keywords:
        return articles

    keywords_lower = [k.lower() for k in keywords]
    result = []
    for article in articles:
        text = (article.get("title", "") + " " + article.get("summary", "")).lower()
        if any(kw in text for kw in keywords_lower):
            result.append(article)
    return result


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _parse_timestamp(entry: dict) -> str:
    """Extracts and normalises published timestamp from RSS entry."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        val = entry.get(field)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc).isoformat()
            except (ValueError, TypeError):
                continue
    return datetime.now(timezone.utc).isoformat()


def _to_timestamp(iso_str: str) -> float:
    """Converts ISO string to Unix timestamp for sorting."""
    try:
        return datetime.fromisoformat(iso_str).timestamp()
    except (ValueError, TypeError):
        return time.time()
