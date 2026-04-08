"""
Skill: technical/signal
Generates a directional signal (Bullish / Neutral / Bearish) based on
price position relative to a set of SMAs.

Input:  price (float), smas (dict[str, float | None])
Output: dict with direction (str) and reason (str)
"""


def derive(price: float, smas: dict[str, float | None]) -> dict:
    """
    Technical signal based on price position relative to available SMAs.

    Logic:
    - Price above ALL SMAs  → Bullish
    - Price below ALL SMAs  → Bearish
    - Otherwise             → Neutral

    Args:
        price: Current asset price.
        smas:  Dict {sma7: ..., sma14: ..., sma30: ...} (None values ignored).

    Returns:
        {"direction": "Bullish" | "Neutral" | "Bearish", "reason": str}
    """
    available = {k: v for k, v in smas.items() if v is not None}

    if not available:
        return {"direction": "Neutral", "reason": "SMAs unavailable"}

    above = sum(1 for v in available.values() if price > v)
    total = len(available)

    if above == total:
        return {"direction": "Bullish", "reason": f"Price above all {total} SMAs"}
    if above == 0:
        return {"direction": "Bearish", "reason": f"Price below all {total} SMAs"}
    return {"direction": "Neutral", "reason": f"Price above {above}/{total} SMAs"}
