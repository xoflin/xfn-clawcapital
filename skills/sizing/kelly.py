"""
Skill: sizing/kelly
Kelly Criterion and Half Kelly for optimal capital fraction sizing.

Input:  win_rate, avg_win_pct, avg_loss_pct, kelly_fraction
Output: fraction of capital to allocate (float, 0–1)
"""


def full_kelly(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """
    Computes the full Kelly fraction.

    Formula: f* = (W × R − (1 − W)) / R
    where R = avg_win / avg_loss, W = win_rate.

    Args:
        win_rate:     Historical win rate (0–1).
        avg_win_pct:  Average gain per trade in % (e.g. 2.0 → 2%).
        avg_loss_pct: Average loss per trade in % (e.g. 1.0 → 1%).

    Returns:
        Kelly fraction (≥ 0). Never negative.
    """
    if avg_loss_pct <= 0 or win_rate <= 0:
        return 0.0
    R = avg_win_pct / avg_loss_pct
    kelly = (win_rate * R - (1 - win_rate)) / R
    return max(0.0, kelly)


def fractional_kelly(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    fraction: float = 0.5,
) -> float:
    """
    Fractional Kelly (typically Half Kelly for lower volatility).

    Args:
        win_rate:     Historical win rate (0–1).
        avg_win_pct:  Average gain per trade in %.
        avg_loss_pct: Average loss per trade in %.
        fraction:     Scale factor (0.5 = Half Kelly).

    Returns:
        Adjusted Kelly fraction (≥ 0).
    """
    return full_kelly(win_rate, avg_win_pct, avg_loss_pct) * fraction
