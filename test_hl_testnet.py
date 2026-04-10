"""
Test script: Hyperliquid Testnet Connection
Verifica se consegues aceder aos fundos na testnet.

Usa HTTP direto à API (sem SDK) para contornar bugs de compatibilidade.

Uso:
  python test_hl_testnet.py

Requer no .env:
  HL_WALLET_ADDRESS
  HL_PRIVATE_KEY
"""

import os
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BASE_URL = "https://api.hyperliquid-testnet.xyz"

# ── Credenciais ───────────────────────────────────────────────────────
wallet      = os.environ.get("HL_WALLET_ADDRESS")
private_key = os.environ.get("HL_PRIVATE_KEY")

if not wallet or not private_key:
    print("❌ Credenciais em falta no .env")
    print("   Preciso de: HL_WALLET_ADDRESS, HL_PRIVATE_KEY")
    sys.exit(1)

print(f"✓ Wallet: {wallet[:10]}...")
print(f"✓ Private Key: configurada\n")


def hl_post(payload: dict) -> dict:
    """Faz um POST à API do Hyperliquid."""
    r = requests.post(
        f"{BASE_URL}/info",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# ── 1. Conectividade ──────────────────────────────────────────────────
print("🔗 Testando conectividade ao TESTNET...\n")
try:
    meta = hl_post({"type": "meta"})
    coins = meta.get("universe", [])
    print(f"✅ TESTNET acessível — {len(coins)} pares disponíveis")
    for c in coins[:5]:
        print(f"   {c.get('name')}")
    print("   ...\n")
except Exception as e:
    print(f"❌ Sem acesso ao TESTNET: {e}")
    sys.exit(1)

# ── 2. Saldo ─────────────────────────────────────────────────────────
print("📊 Verificando saldo...\n")
try:
    state = hl_post({"type": "clearinghouseState", "user": wallet})
    margin = state.get("marginSummary", {})
    account_value = float(margin.get("accountValue", 0))
    withdrawable  = float(state.get("withdrawable", 0))

    if account_value > 0:
        print(f"💰 Account Value: ${account_value:,.2f}")
        print(f"💵 Withdrawable:  ${withdrawable:,.2f}\n")
    else:
        print("⚠️  Saldo zero — ainda não recebeste testnet funds?")
        print("   Pede em: https://app.hyperliquid-testnet.xyz/drip\n")
except Exception as e:
    print(f"❌ Erro ao fetchar saldo: {e}\n")

# ── 3. Posições abertas ───────────────────────────────────────────────
print("📈 Posições abertas...\n")
try:
    state = hl_post({"type": "clearinghouseState", "user": wallet})
    positions = [
        p for p in state.get("assetPositions", [])
        if float(p["position"]["szi"]) != 0
    ]
    if positions:
        print(f"✓ {len(positions)} posição(ões) abertas:")
        for p in positions:
            pos = p["position"]
            print(f"  {pos['coin']}: {pos['szi']} @ entry ${pos.get('entryPx', '?')}")
    else:
        print("✓ Sem posições abertas (normal para novo trader)")
except Exception as e:
    print(f"❌ Erro ao fetchar posições: {e}\n")

# ── 4. Ordens abertas ─────────────────────────────────────────────────
print("\n📋 Ordens abertas...\n")
try:
    orders = hl_post({"type": "openOrders", "user": wallet})
    if orders:
        print(f"✓ {len(orders)} ordem(ns) abertas:")
        for o in orders:
            print(f"  {o}")
    else:
        print("✓ Sem ordens abertas")
except Exception as e:
    print(f"❌ Erro ao fetchar ordens: {e}\n")

# ── 5. SDK Exchange (para fazer ordens) ───────────────────────────────
print("\n🔑 Testando Exchange SDK (necessário para ordens)...\n")
try:
    import eth_account
    from hyperliquid.exchange import Exchange

    account = eth_account.Account.from_key(private_key)

    # Obter meta e spot_meta via HTTP primeiro para evitar bug no SDK
    meta_resp      = hl_post({"type": "meta"})
    spot_meta_resp = hl_post({"type": "spotMeta"})

    # Workaround: a testnet tem pares spot com índices de tokens fora
    # do intervalo — filtramos os pares inválidos antes de passar ao SDK
    tokens = spot_meta_resp.get("tokens", [])
    valid_universe = [
        s for s in spot_meta_resp.get("universe", [])
        if len(s.get("tokens", [])) >= 2
        and max(s["tokens"]) < len(tokens)
    ]
    spot_meta_fixed = {"universe": valid_universe, "tokens": tokens}

    exchange = Exchange(
        wallet=account,
        base_url=BASE_URL,
        account_address=wallet,
        meta=meta_resp,
        spot_meta=spot_meta_fixed,
    )
    print("✅ Exchange SDK inicializado — pronto para ordens!")
except Exception as e:
    import traceback
    print(f"⚠️  Exchange SDK falhou: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("PRÓXIMOS PASSOS:")
print("=" * 60)
print("1. Se viste saldo > 0: Podes fazer trading na testnet ✓")
print("2. Se saldo = 0: Pede testnet funds em:")
print("   https://app.hyperliquid-testnet.xyz/drip")
print("3. Para correr o bot na testnet: HL_MODE=test no .env")
print("=" * 60)
