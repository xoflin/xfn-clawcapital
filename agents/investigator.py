"""
Agent: Investigator
Uses Gemini 2.5 Flash to synthesise data from multiple sources
and produce a structured briefing for the manager agent.

Sources consulted per cycle:
  1. FRED API            → macro (rates, inflation, yield curve)
  2. CoinGecko           → prices and 24h change (batch, 1 req)
  3. Alpha Vantage       → RSI + MACD (3 req/ticker — use sparingly)
  4. CryptoCompare News  → headlines (free, no key required)
  5. RSS Feeds           → CoinDesk, CoinTelegraph, etc.
  6. Gemini 2.5 Flash    → narrative synthesis + structured briefing

Alpha Vantage quota: 25 req/day.
  max_av_tickers controls how many tickers receive AV analysis (default 2).

Output: "briefing" dict ready to be consumed by the manager agent.
"""

import json
import os
import time
from datetime import datetime, timezone

from google import genai

from skills.data_fetchers.fred import fetch_macro_snapshot
from skills.data_fetchers.coingecko import CoinGeckoClient
from skills.data_fetchers.alpha_vantage import AlphaVantageClient
from skills.data_fetchers.cryptocompare_news import fetch_news as fetch_cc_news, format_for_prompt as cc_format
from skills.data_fetchers.fear_greed import (
    fetch_fear_greed_index,
    fear_greed_signal,
)
from skills.data_fetchers.rss_feeds import fetch_rss_feeds, filter_articles_by_keywords
from skills.data_fetchers.defillama import fetch_defi_snapshot
from risk.quota import QuotaTracker
from skills.data_fetchers.coinglass import fetch_derivatives_snapshot
from skills.learning.trade_analyzer import get_prompt_context as _get_lessons


_MODEL_PRIMARY  = "gemini-2.5-flash"
_MODEL_FALLBACK = "gemini-2.5-flash-lite"
_MODEL_NAME     = _MODEL_PRIMARY  # used for display


# ------------------------------------------------------------------
# Investigator prompt
# ------------------------------------------------------------------

_INVESTIGATOR_PROMPT = """\
You are a senior quantitative analyst specialised in crypto assets.
You have access to the following real-time data:

=== MACRO CONTEXT (FRED) ===
{macro_context}

=== MARKET DATA (CoinGecko) ===
{market_data}

=== TECHNICAL INDICATORS (Alpha Vantage) ===
{technical_data}

=== SOCIAL SENTIMENT PILLAR ===

--- CryptoPanic Headlines ---
{news_data}

--- Fear & Greed Index (Alternative.me) ---
{fear_greed_data}

--- RSS News Feeds ---
{rss_data}

=== DEFI ECOSYSTEM (DeFiLlama) ===
{defi_data}

=== DERIVATIVES MARKET (CoinGlass) ===
{derivatives_data}

=== HISTORICAL PERFORMANCE (Learning from past trades) ===
{lessons_data}

---
Based on this data AND your past performance, produce a structured JSON briefing with EXACTLY this format:

{{
  "macro_summary": "<2-3 sentences on the macro environment and its impact on crypto>",
  "market_summary": "<2-3 sentences on current market state and momentum>",
  "technical_summary": "<2-3 sentences on key technical indicators>",
  "sentiment_summary": "<1-2 sentences on market sentiment>",
  "risk_factors": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "opportunities": ["<opportunity 1>", "<opportunity 2>"],
  "overall_bias": "<Bullish|Neutral|Bearish>",
  "bias_confidence": <0.0 to 1.0>,
  "assets_ranked": [
    {{
      "ticker": "<TICKER>",
      "thesis": "<investment thesis in 1 sentence>",
      "technical_score": <-1.0 to 1.0>,
      "sentiment_score": <-1.0 to 1.0>,
      "priority": <1, 2 or 3 — 1 is highest priority>
    }}
  ],
  "investigator_notes": "<any additional observations relevant to the manager>"
}}

Respond with JSON ONLY. No additional text, no markdown, no explanations.
"""


# ------------------------------------------------------------------
# Investigator Agent
# ------------------------------------------------------------------

class InvestigatorAgent:
    """
    Collects data from all sources and produces a structured briefing
    for the manager agent to make the final decision.

    Args:
        gemini_api_key:        Gemini API key (Flash).
        coingecko_api_key:     CoinGecko key (optional — free without key).
        alpha_vantage_key:     Alpha Vantage key (free, 25 req/day).
        fred_api_key:          FRED API key (free).
        cryptocompare_api_key: CryptoCompare API key (optional — higher rate limit).
        max_av_tickers:        Max tickers with Alpha Vantage analysis (default 2).
    """

    def __init__(
        self,
        gemini_api_key: str,
        cryptopanic_token: str | None = None,   # kept for backwards compat, unused
        coingecko_api_key: str | None = None,
        alpha_vantage_key: str | None = None,
        fred_api_key: str | None = None,
        cryptocompare_api_key: str | None = None,
        max_av_tickers: int = 2,
    ):
        self.alpha_vantage_key      = alpha_vantage_key
        self.fred_api_key           = fred_api_key
        self.cryptocompare_api_key  = cryptocompare_api_key
        self.max_av_tickers         = max_av_tickers

        self._coingecko = CoinGeckoClient(api_key=coingecko_api_key)
        self._genai     = genai.Client(api_key=gemini_api_key)
        self._quota     = QuotaTracker()

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _collect_macro(self) -> str:
        """Fetches FRED macro snapshot. Returns formatted string for the prompt."""
        if not self.fred_api_key:
            return "FRED API not configured — macro data unavailable."
        try:
            snapshot = fetch_macro_snapshot(api_key=self.fred_api_key)
            lines = []
            for series_id, data in snapshot["indicators"].items():
                label = data.get("label", series_id)
                val   = data.get("latest_value")
                date  = data.get("latest_date", "")
                if val is not None:
                    lines.append(f"  {label}: {val:.2f} ({date})")
                else:
                    lines.append(f"  {label}: N/A")
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching FRED data: {e}"

    def _collect_market(self, tickers: list[str]) -> str:
        """CoinGecko batch snapshot. Returns formatted string."""
        def _fmt_price(p: float) -> str:
            if p >= 1000:   return f"${p:,.0f}"
            if p >= 1:      return f"${p:,.2f}"
            return f"${p:,.4f}"

        try:
            snapshots = self._coingecko.get_batch_snapshots(tickers)
            lines = []
            for s in snapshots:
                ticker = s.get("ticker", "?")
                price  = s.get("price", 0)
                chg    = s.get("change_24h_pct", 0)
                vol    = s.get("volume_24h", 0)
                mcap   = s.get("market_cap", 0)
                lines.append(
                    f"  {ticker}: {_fmt_price(price)} | 24h: {chg:+.2f}% | "
                    f"Vol: ${vol:,.0f} | MCap: ${mcap:,.0f}"
                )
            return "\n".join(lines) if lines else "Market data unavailable."
        except Exception as e:
            return f"CoinGecko error: {e}"

    def _collect_technical(self, tickers: list[str]) -> str:
        """RSI + MACD via Alpha Vantage (limited to max_av_tickers).
        Each ticker consumes 3 quota units (snapshot + RSI + MACD)."""
        if not self.alpha_vantage_key:
            return "Alpha Vantage not configured — technical indicators unavailable."

        av = AlphaVantageClient(api_key=self.alpha_vantage_key)
        lines = []
        for ticker in tickers[:self.max_av_tickers]:
            # get_technical_report makes 3 real API calls — consume 3 quota units upfront
            allowed, reason = self._quota.check_and_consume("alpha_vantage", units=3)
            if not allowed:
                lines.append(f"  skipped — {reason}")
                break  # same reason applies to all remaining tickers
            try:
                report = av.get_technical_report(ticker)
                rsi    = report.get("rsi_latest") or {}
                macd   = report.get("macd_latest") or {}
                signal = report.get("signal", {})
                lines.append(
                    f"  {ticker}: RSI={rsi.get('rsi', 'N/A')} | "
                    f"MACD hist={macd.get('histogram', 'N/A')} | "
                    f"Signal: {signal.get('direction', 'N/A')} — {signal.get('reason', '')}"
                )
                time.sleep(12)  # 5 req/min on free plan → ~12s between 3-req reports
            except RuntimeError as e:
                # AV returned a rate-limit error — exhaust quota tracker to block further calls
                is_ratelimit = "rate limit" in str(e).lower()
                if is_ratelimit:
                    self._quota.mark_exhausted("alpha_vantage")
                    lines.append(f"  {ticker}: AV error — quota exhausted (daily limit reached)")
                else:
                    lines.append(f"  {ticker}: AV error — {str(e)[:60]}")
                break  # no point retrying remaining tickers
            except Exception as e:
                lines.append(f"  {ticker}: AV error — {str(e)[:60]}")

        if not lines:
            return "No tickers with technical analysis available."
        return "\n".join(lines)

    def _collect_news(self, tickers: list[str]) -> str:
        """CryptoCompare News headlines (API key optional — higher rate limit when set)."""
        try:
            articles = fetch_cc_news(
                tickers=tickers,
                max_results=20,
                api_key=self.cryptocompare_api_key,
            )
            return cc_format(articles, max_items=15)
        except Exception as e:
            return f"CryptoCompare News error: {e}"

    def _collect_fear_greed(self) -> str:
        """Fetches Fear & Greed Index from Alternative.me."""
        try:
            data = fetch_fear_greed_index(limit=7)
            if "error" in data:
                return f"Fear & Greed unavailable: {data['error']}"

            current = data.get("current", {})
            value = current.get("value", 50)
            classification = current.get("classification", "Neutral")
            signal = fear_greed_signal(value)

            # Build history trend
            history = data.get("history", [])[:3]
            trend_str = " ← ".join([str(h.get("value", 50)) for h in reversed(history)])

            return (
                f"  Current: {value} ({classification})\n"
                f"  Signal: {signal:+.2f}\n"
                f"  7-day trend: {trend_str}"
            )
        except Exception as e:
            return f"Fear & Greed error: {e}"

    def _collect_rss_feeds(self, tickers: list[str]) -> str:
        """Fetches and filters RSS feeds by crypto keywords."""
        try:
            result = fetch_rss_feeds(max_per_feed=5)
            articles = result.get("articles", [])

            # Filter by crypto keywords or tickers
            keywords = tickers + ["crypto", "bitcoin", "ethereum", "defi", "trading"]
            filtered = filter_articles_by_keywords(articles, keywords)[:10]

            if not filtered:
                return "No relevant RSS articles found."

            lines = []
            for article in filtered:
                source = article.get("source", "unknown").upper()
                title = article.get("title", "")[:80]
                pub = article.get("published_at", "")[:10]
                lines.append(f"  [{source}] {title} ({pub})")

            # Add feed status
            feed_status = result.get("feed_status", {})
            status_summary = " | ".join(
                [
                    f"{name}: {data.get('article_count', 0)} articles"
                    for name, data in feed_status.items()
                    if data.get("status") == "ok"
                ]
            )

            return "\n".join(lines) + f"\n\n  Feed status: {status_summary}"
        except Exception as e:
            return f"RSS feeds error: {e}"

    def _collect_defi(self) -> str:
        """Fetches DeFi TVL snapshot from DeFiLlama."""
        try:
            snapshot = fetch_defi_snapshot()  # public API, no auth
            g = snapshot.get("global", {})
            tvl = g.get("current_tvl_usd", 0)
            chg = g.get("tvl_change_7d_pct")
            signal = g.get("signal", 0.0)

            chains = snapshot.get("chains", [])
            chain_lines = [
                f"  {c['chain']}: ${c['tvl_usd']:,.0f}"
                for c in chains[:5]
            ]

            chg_str = f"{chg:+.2f}%" if chg is not None else "N/A"
            return (
                f"  Total DeFi TVL: ${tvl:,.0f} | 7d change: {chg_str} | Signal: {signal:+.2f}\n"
                + "\n".join(chain_lines)
            )
        except Exception as e:
            return f"DeFiLlama error: {e}"

    def _collect_derivatives(self, tickers: list[str]) -> str:
        """Fetches funding rates and long/short ratios (Bybit → Binance → OKX fallback)."""
        try:
            snapshot = fetch_derivatives_snapshot(tickers)
            lines = []
            failed: list[str] = []

            for fr in snapshot.get("funding_rates", []):
                ticker = fr.get("ticker", "?")
                if fr.get("interpretation") == "No data":
                    failed.append(ticker)
                    continue
                rate   = fr.get("avg_funding_rate_pct", 0)
                interp = fr.get("interpretation", "")
                lines.append(f"  {ticker} Funding: {rate:+.4f}% — {interp}")

            for ls in snapshot.get("long_short_ratios", []):
                ticker   = ls.get("ticker", "?")
                if ls.get("interpretation") == "No data":
                    continue  # already noted in funding_rates pass
                long_pct  = ls.get("long_pct", 50)
                short_pct = ls.get("short_pct", 50)
                interp    = ls.get("interpretation", "")
                lines.append(f"  {ticker} L/S: {long_pct:.1f}% / {short_pct:.1f}% — {interp}")

            if not lines:
                return "Derivatives data unavailable."
            if failed:
                lines.append(f"  (no data for: {', '.join(failed)})")
            return "\n".join(lines)
        except Exception as e:
            return f"CoinGlass error: {e}"

    # ------------------------------------------------------------------
    # Synthesis with Gemini Flash
    # ------------------------------------------------------------------

    def _synthesize(
        self,
        macro: str,
        market: str,
        technical: str,
        news: str,
        fear_greed: str,
        rss_feeds: str,
        defi: str,
        derivatives: str,
    ) -> dict:
        """Calls Gemini 2.5 Flash and returns the structured briefing."""
        lessons = _get_lessons() or "No trade history yet — first cycle."
        prompt = _INVESTIGATOR_PROMPT.format(
            macro_context=macro,
            market_data=market,
            technical_data=technical,
            news_data=news,
            fear_greed_data=fear_greed,
            rss_data=rss_feeds,
            defi_data=defi,
            derivatives_data=derivatives,
            lessons_data=lessons,
        )

        allowed, reason = self._quota.check_and_consume("gemini_flash")
        if not allowed:
            raise RuntimeError(f"Gemini Flash quota: {reason}")

        last_err = None
        for model in (_MODEL_PRIMARY, _MODEL_FALLBACK):
            try:
                response = self._genai.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                if model != _MODEL_PRIMARY:
                    print(f"  [Gemini] ⚠ using fallback model: {model}")
                break
            except Exception as e:
                last_err = e
                continue
        else:
            raise RuntimeError(f"All Gemini models failed: {last_err}")
        raw = response.text.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        return json.loads(raw)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, watchlist: list[str]) -> dict:
        """
        Runs the full investigation cycle for the given watchlist.

        Args:
            watchlist: List of tickers (e.g. ["BTC", "ETH", "SOL"]).

        Returns:
            {
              "agent": "investigator",
              "timestamp": str,
              "watchlist": list[str],
              "raw_data": { macro, market, technical, news },
              "briefing": { ... }   ← Gemini Flash output
            }
        """
        ts = datetime.now(timezone.utc).isoformat()
        LW = 14   # label column width
        DW = 62   # data column width

        # ── helpers ──────────────────────────────────────────────────
        _BAD = ("error", "unavailable", "not configured", "skipped —", "av error", "no data", "no relevant")

        def _ok(data: str) -> bool:
            return not any(b in data.lower() for b in _BAD)

        def _line(label: str, data: str, summary: str | None = None) -> str:
            icon = "✓" if _ok(data) else "✗"
            s    = (summary or data.strip().split("\n")[0].lstrip())[:DW]
            return f"  {label:<{LW}}{icon} │ {s}"

        # ── 1. FRED ──────────────────────────────────────────────────
        macro = self._collect_macro()
        # Show only first indicator (most relevant)
        macro_summary = macro.strip().split("\n")[0].lstrip()
        print(_line("FRED", macro, macro_summary))

        # ── 2. CoinGecko ─────────────────────────────────────────────
        market = self._collect_market(watchlist)
        time.sleep(1)
        cg_parts = []
        for _l in market.strip().split("\n"):
            segs = [s.strip() for s in _l.split("|")]
            if len(segs) >= 2:
                # "  BTC: $73,006 | 24h: +0.61% | ..." → "BTC $73,006 +0.61%"
                t = segs[0].lstrip().replace(": $", " $").replace(":", "").strip()
                c = segs[1].replace("24h:", "").strip()
                cg_parts.append(f"{t} {c}")
        print(_line("CoinGecko", market, "  ".join(cg_parts) or None))

        # ── 3. Alpha Vantage ─────────────────────────────────────────
        technical = self._collect_technical(watchlist)
        av_parts = []
        for _l in technical.strip().split("\n"):
            _l = _l.lstrip()
            if "RSI=" in _l:
                _t   = _l.split(":")[0].strip()
                _rsi = next((s.strip() for s in _l.split("|") if "RSI=" in s), "")
                _sig = next((s.split("—")[0].replace("Signal:", "").strip()
                             for s in _l.split("|") if "Signal:" in s), "")
                av_parts.append(f"{_t} {_rsi} {_sig}".strip())
            elif "skipped" in _l or "error" in _l.lower():
                av_parts.append(_l[:50])
        print(_line("AlphaVantage", technical, "  ".join(av_parts) or None))

        # ── 4. News ──────────────────────────────────────────────────
        news = self._collect_news(watchlist)
        n_news = sum(1 for _l in news.strip().split("\n") if _l.strip().startswith("["))
        print(_line("News", news, f"{n_news} headlines" if n_news else None))

        # ── 5. Fear & Greed ──────────────────────────────────────────
        fear_greed = self._collect_fear_greed()
        fg_first = fear_greed.strip().split("\n")[0].lstrip().replace("Current: ", "")
        print(_line("Fear&Greed", fear_greed, fg_first))

        # ── 6. RSS ───────────────────────────────────────────────────
        rss_feeds = self._collect_rss_feeds(watchlist)
        n_rss = sum(1 for _l in rss_feeds.strip().split("\n") if _l.strip().startswith("["))
        print(_line("RSS", rss_feeds, f"{n_rss} articles" if n_rss else None))

        # ── 7. DeFiLlama ─────────────────────────────────────────────
        defi = self._collect_defi()
        _defi_parts = defi.strip().split("\n")[0].lstrip().split("|")
        _defi_tvl   = _defi_parts[0].replace("Total DeFi TVL:", "TVL:").strip()
        _defi_chg   = _defi_parts[1].replace("7d change:", "7d:").strip() if len(_defi_parts) > 1 else ""
        defi_summary = f"{_defi_tvl}  {_defi_chg}".strip()
        print(_line("DeFiLlama", defi, defi_summary or None))

        # ── 8. CoinGlass ─────────────────────────────────────────────
        derivatives = self._collect_derivatives(watchlist)
        print(_line("CoinGlass", derivatives))

        # ── 9. Gemini Flash synthesis ─────────────────────────────────
        _gem_ok = True
        try:
            briefing = self._synthesize(
                macro, market, technical, news,
                fear_greed, rss_feeds, defi, derivatives,
            )
            gem_summary = (
                f"{briefing.get('overall_bias', 'N/A')}  "
                f"conf={briefing.get('bias_confidence', 0):.2f}"
            )
        except json.JSONDecodeError as e:
            _gem_ok     = False
            gem_summary = f"JSON parse error — {str(e)[:55]}"
            briefing = {
                "macro_summary":      macro[:300],
                "market_summary":     market[:300],
                "technical_summary":  technical[:300],
                "sentiment_summary":  f"{news[:100]} | FnG: {fear_greed[:100]}",
                "risk_factors":       [],
                "opportunities":      [],
                "overall_bias":       "Neutral",
                "bias_confidence":    0.0,
                "assets_ranked":      [],
                "investigator_notes": "Automatic synthesis failed — raw data included.",
            }

        print(f"  [{_MODEL_PRIMARY}]  {'✓' if _gem_ok else '✗'} │ {gem_summary}")

        return {
            "agent":     "investigator",
            "timestamp": ts,
            "watchlist": watchlist,
            "raw_data": {
                "macro":       macro,
                "market":      market,
                "technical":   technical,
                "news":        news,
                "fear_greed":  fear_greed,
                "rss_feeds":   rss_feeds,
                "defi":        defi,
                "derivatives": derivatives,
            },
            "briefing": briefing,
        }


# ------------------------------------------------------------------
# Direct execution (test/debug)
# ------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    agent = InvestigatorAgent(
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        cryptopanic_token=os.environ["CRYPTOPANIC_TOKEN"],
        coingecko_api_key=os.environ.get("COINGECKO_API_KEY"),
        alpha_vantage_key=os.environ.get("ALPHA_VANTAGE_API_KEY"),
        fred_api_key=os.environ.get("FRED_API_KEY"),
        max_av_tickers=2,
    )

    result = agent.run(watchlist=["BTC", "ETH", "SOL"])
    print("\n=== BRIEFING ===")
    print(json.dumps(result["briefing"], indent=2, ensure_ascii=False))
