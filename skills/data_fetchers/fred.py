"""
Skill: data_fetchers/fred
Connector for the FRED API (Federal Reserve Economic Data).
Fetches macroeconomic data: interest rates, inflation, interbank spreads.

Input:  api_key (str), series_id (str), limit (int)
Output: dict with latest value + recent history

Default series:
  FEDFUNDS     — Fed Funds Rate (US benchmark interest rate)
  CPIAUCSL     — CPI (US inflation, monthly data)
  T10Y2Y       — 10y-2y spread (yield curve, recession signal)
  DFF          — Effective Federal Funds Rate (daily)
  SOFR         — Secured Overnight Financing Rate (interbank)
  BAMLH0A0HYM2 — High Yield OAS (credit risk appetite)
"""

import requests
from datetime import datetime, timezone

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

DEFAULT_SERIES: dict[str, str] = {
    "FEDFUNDS":     "Fed Funds Rate (%)",
    "CPIAUCSL":     "CPI Inflation YoY",
    "T10Y2Y":       "10y-2y Spread (yield curve)",
    "DFF":          "Effective Fed Funds Rate (daily)",
    "SOFR":         "SOFR Interbank Rate",
    "BAMLH0A0HYM2": "High Yield Spread (credit risk)",
}


def fetch_series(
    api_key: str,
    series_id: str,
    limit: int = 5,
) -> dict:
    """
    Fetches the most recent observations for a FRED series.

    Args:
        api_key:   FRED API key (free at fred.stlouisfed.org).
        series_id: Series ID (e.g. "FEDFUNDS", "CPIAUCSL").
        limit:     Number of most recent observations to return.

    Returns:
        {
          "series_id": str,
          "label": str,
          "latest_value": float | None,
          "latest_date": str,
          "observations": [{"date": str, "value": float | None}, ...],
          "fetched_at": str,
        }
    """
    params = {
        "series_id":         series_id,
        "api_key":           api_key,
        "file_type":         "json",
        "sort_order":        "desc",
        "limit":             limit,
        "observation_start": "2020-01-01",
    }
    response = requests.get(FRED_BASE_URL, params=params, timeout=10)
    response.raise_for_status()

    raw_obs = response.json().get("observations", [])
    observations = []
    for obs in raw_obs:
        raw_val = obs.get("value", ".")
        value = None if raw_val == "." else float(raw_val)
        observations.append({"date": obs["date"], "value": value})

    # Observations returned in descending order — most recent is first
    latest = observations[0] if observations else {"date": "", "value": None}

    return {
        "series_id":    series_id,
        "label":        DEFAULT_SERIES.get(series_id, series_id),
        "latest_value": latest["value"],
        "latest_date":  latest["date"],
        "observations": list(reversed(observations)),  # chronological
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
    }


def fetch_macro_snapshot(api_key: str, series: dict[str, str] | None = None) -> dict:
    """
    Fetches a complete macro snapshot across multiple FRED series.

    Args:
        api_key: FRED API key.
        series:  Dict {series_id: label} to query. Defaults to DEFAULT_SERIES.

    Returns:
        {
          "fetched_at": str,
          "indicators": {
            "FEDFUNDS": {"label": ..., "latest_value": ..., "latest_date": ...},
            ...
          }
        }
    """
    if series is None:
        series = DEFAULT_SERIES

    indicators = {}
    for series_id in series:
        try:
            result = fetch_series(api_key, series_id, limit=2)
            indicators[series_id] = {
                "label":        result["label"],
                "latest_value": result["latest_value"],
                "latest_date":  result["latest_date"],
            }
        except Exception as e:
            indicators[series_id] = {
                "label":        series.get(series_id, series_id),
                "latest_value": None,
                "latest_date":  "",
                "error":        str(e),
            }

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "indicators": indicators,
    }
