"""
Skill: data_fetchers/defillama
Connector for the DeFiLlama API — TVL and DeFi protocol data.

Public API, no authentication required.
Docs: https://defillama.com/docs/api

Data provided:
  - Total Value Locked (TVL) across all DeFi
  - TVL per chain (Ethereum, Solana, BSC, etc.)
  - Protocol-level TVL (Uniswap, Aave, etc.)
  - TVL historical trend

Why it matters:
  - Rising TVL → capital flowing into DeFi → bullish signal
  - Falling TVL → capital leaving → bearish / risk-off
  - Chain-level TVL tracks ecosystem health (e.g. Solana vs ETH)
"""

import requests
from datetime import datetime, timezone

DEFILLAMA_BASE = "https://api.llama.fi"

# Chains of interest mapped to DeFiLlama identifiers
CHAINS_OF_INTEREST = ["Ethereum", "Solana", "BSC", "Arbitrum", "Base", "Avalanche"]

# Top protocols to track
TOP_PROTOCOLS = [
    "uniswap", "aave", "lido", "maker", "curve", "compound",
    "jupiter", "raydium", "jito",
]


def fetch_global_tvl() -> dict:
    """
    Fetches total DeFi TVL and recent trend.

    Returns:
        {
            "current_tvl_usd": float,
            "tvl_change_7d_pct": float | None,
            "signal": float (-1 to +1),
        }
    """
    try:
        # Historical TVL (last 30 days)
        response = requests.get(f"{DEFILLAMA_BASE}/v2/historicalChainTvl", timeout=10)
        response.raise_for_status()
        history = response.json()

        if not history or len(history) < 7:
            return {"current_tvl_usd": 0, "tvl_change_7d_pct": None, "signal": 0.0}

        current = history[-1].get("tvl", 0)
        week_ago = history[-7].get("tvl", 0)

        change_7d = ((current - week_ago) / week_ago * 100) if week_ago else 0.0
        # Map change to signal: -10% → -1, +10% → +1, clamped
        signal = max(-1.0, min(1.0, change_7d / 10.0))

        return {
            "current_tvl_usd": current,
            "tvl_change_7d_pct": round(change_7d, 2),
            "signal": round(signal, 3),
        }

    except Exception as e:
        return {"current_tvl_usd": 0, "tvl_change_7d_pct": None, "signal": 0.0, "error": str(e)}


def fetch_chain_tvl() -> list[dict]:
    """
    Fetches TVL per chain, filtered to chains of interest.

    Returns:
        [{"chain": str, "tvl_usd": float}, ...]
    """
    try:
        response = requests.get(f"{DEFILLAMA_BASE}/v2/chains", timeout=10)
        response.raise_for_status()
        chains = response.json()

        result = []
        for chain in chains:
            name = chain.get("name", "")
            if name in CHAINS_OF_INTEREST:
                result.append(
                    {
                        "chain": name,
                        "tvl_usd": chain.get("tvl", 0),
                    }
                )

        result.sort(key=lambda x: x["tvl_usd"], reverse=True)
        return result

    except Exception as e:
        return [{"error": str(e)}]


def fetch_protocol_tvl(protocol_slug: str) -> dict:
    """
    Fetches TVL for a specific protocol.

    Args:
        protocol_slug: DeFiLlama slug (e.g. "uniswap", "aave").

    Returns:
        {"protocol": str, "tvl_usd": float, "change_1d_pct": float}
    """
    try:
        response = requests.get(f"{DEFILLAMA_BASE}/protocol/{protocol_slug}", timeout=10)
        response.raise_for_status()
        data = response.json()

        tvl_series = data.get("tvl", [])
        current_tvl = tvl_series[-1].get("totalLiquidityUSD", 0) if tvl_series else 0
        prev_tvl = tvl_series[-2].get("totalLiquidityUSD", 0) if len(tvl_series) >= 2 else current_tvl
        change_1d = ((current_tvl - prev_tvl) / prev_tvl * 100) if prev_tvl else 0.0

        return {
            "protocol": protocol_slug,
            "tvl_usd": current_tvl,
            "change_1d_pct": round(change_1d, 2),
        }

    except Exception as e:
        return {"protocol": protocol_slug, "tvl_usd": 0, "error": str(e)}


def fetch_defi_snapshot() -> dict:
    """
    Full DeFiLlama snapshot: global TVL + chain breakdown.
    Used by InvestigatorAgent.

    Returns:
        {
            "global": {...},
            "chains": [...],
            "fetched_at": str,
        }
    """
    return {
        "global": fetch_global_tvl(),
        "chains": fetch_chain_tvl(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
