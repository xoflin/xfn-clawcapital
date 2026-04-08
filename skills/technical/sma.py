"""
Skill: technical/sma
Simple Moving Average (SMA) calculations over price series.

Input:  list of closing prices (float) + period (int)
Output: SMA value (float | None)
"""


def calculate(closes: list[float], period: int) -> float | None:
    """
    Computes the SMA for the last `period` closing prices.

    Args:
        closes: Time series of closing prices (chronological order).
        period: Number of candles to include.

    Returns:
        SMA value rounded to 6 decimal places, or None if insufficient data.
    """
    if len(closes) < period:
        return None
    window = closes[-period:]
    return round(sum(window) / len(window), 6)


def calculate_many(
    closes: list[float],
    periods: list[int],
) -> dict[str, float | None]:
    """
    Computes multiple SMAs in one call.

    Args:
        closes:  Price series.
        periods: List of periods (e.g. [7, 14, 30]).

    Returns:
        Dict {sma7: ..., sma14: ..., sma30: ...}.
    """
    return {f"sma{p}": calculate(closes, p) for p in periods}


def pct_diff(price: float, sma: float | None) -> float | None:
    """
    Percentage difference between the current price and an SMA.

    Returns:
        Percentage rounded to 4 decimal places, or None if SMA unavailable.
    """
    if sma is None or sma == 0:
        return None
    return round(((price - sma) / sma) * 100, 4)
