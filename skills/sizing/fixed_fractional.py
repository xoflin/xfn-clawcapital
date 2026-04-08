"""
Skill: sizing/fixed_fractional
Fixed Fractional / Fixed Risk position sizing.

Input:  capital, risk_pct
Output: USD amount to risk on the trade (float)
"""


def risk_amount(capital: float, risk_pct: float) -> float:
    """
    Computes the USD amount to risk based on a fixed percentage of capital.

    Args:
        capital:  Total available capital (USD).
        risk_pct: Percentage of capital to risk per trade (e.g. 1.0 → 1%).

    Returns:
        USD amount (≥ 0).
    """
    if capital <= 0 or risk_pct <= 0:
        return 0.0
    return capital * (risk_pct / 100)


def position_size_from_risk(
    risk_usd: float,
    stop_loss_pct: float,
) -> float:
    """
    Converts a USD risk amount into a position size.

    Formula: size = risk_usd / (stop_loss_pct / 100)

    Args:
        risk_usd:      Maximum amount to lose on this trade (USD).
        stop_loss_pct: Distance to stop loss as a percentage (e.g. 3.0 → 3%).

    Returns:
        Position size in USD (≥ 0).
    """
    if stop_loss_pct <= 0:
        return 0.0
    return risk_usd / (stop_loss_pct / 100)
