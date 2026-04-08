"""
Skill: data_fetchers/fear_greed
Connector for the Alternative.me Fear & Greed Index API.

The Fear & Greed Index is a sentiment gauge for crypto markets:
  - 0-24: Extreme Fear
  - 25-44: Fear
  - 45-54: Neutral
  - 55-74: Greed
  - 75-100: Extreme Greed

API: https://api.alternative.me/fng/ (no authentication required)
Limit: ~100 req/hour (public, no quota)

Output: index value (0-100) + classification + recent history
"""

import requests
from datetime import datetime, timezone

FEAR_GREED_API = "https://api.alternative.me/fng/"


def fetch_fear_greed_index(limit: int = 30) -> dict:
    """
    Fetches the current Fear & Greed Index and recent history.

    Args:
        limit: Number of historical data points to return (max 365).

    Returns:
        {
            "current": {
                "value": int (0-100),
                "classification": str ("Extreme Fear", "Fear", etc),
                "timestamp": str (ISO),
            },
            "history": [
                {"value": int, "classification": str, "timestamp": str},
                ...
            ]
        }
    """
    try:
        response = requests.get(
            FEAR_GREED_API,
            params={"limit": limit},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "success":
            raise ValueError(f"Fear & Greed API error: {data.get('status_code')}")

        # Parse current value
        current_entry = data.get("data", [{}])[0]
        current_value = int(current_entry.get("value", 50))
        current_timestamp = int(current_entry.get("timestamp", 0))

        # Parse history
        history = []
        for entry in data.get("data", []):
            try:
                history.append(
                    {
                        "value": int(entry.get("value", 50)),
                        "classification": entry.get("value_classification", "Neutral"),
                        "timestamp": datetime.fromtimestamp(
                            int(entry.get("timestamp", 0)), tz=timezone.utc
                        ).isoformat(),
                    }
                )
            except (ValueError, TypeError):
                continue

        return {
            "current": {
                "value": current_value,
                "classification": current_entry.get("value_classification", "Neutral"),
                "timestamp": datetime.fromtimestamp(
                    current_timestamp, tz=timezone.utc
                ).isoformat(),
            },
            "history": history,
        }

    except requests.RequestException as e:
        return {
            "current": {
                "value": 50,  # Neutral fallback
                "classification": "Neutral",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "error": str(e),
            "history": [],
        }


def classify_fear_greed(value: int) -> str:
    """
    Classifies Fear & Greed index value.

    Args:
        value: Index value (0-100).

    Returns:
        Classification string.
    """
    if value < 25:
        return "Extreme Fear"
    elif value < 45:
        return "Fear"
    elif value < 55:
        return "Neutral"
    elif value < 75:
        return "Greed"
    else:
        return "Extreme Greed"


def fear_greed_signal(value: int) -> float:
    """
    Converts Fear & Greed index to a sentiment signal (-1 to +1).

    Args:
        value: Index value (0-100).

    Returns:
        Signal: -1 (extreme fear) to +1 (extreme greed).
    """
    # Linear mapping: 0 → -1, 50 → 0, 100 → +1
    return (value - 50) / 50
