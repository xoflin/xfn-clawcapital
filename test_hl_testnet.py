"""
Test script: Hyperliquid Testnet Connection
Verifica se consegues aceder aos fundos na testnet.

Uso:
  python test_hl_testnet.py

Requer no .env:
  HL_WALLET_ADDRESS
  HL_PRIVATE_KEY
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Check credentials
wallet = os.environ.get("HL_WALLET_ADDRESS")
private_key = os.environ.get("HL_PRIVATE_KEY")

if not wallet or not private_key:
    print("❌ Credenciais em falta no .env")
    print("   Preciso de: HL_WALLET_ADDRESS, HL_PRIVATE_KEY")
    sys.exit(1)

print(f"✓ Wallet: {wallet[:10]}...")
print(f"✓ Private Key: configurada\n")

# Import Hyperliquid SDK
try:
    from hyperliquid.info import Info
    import eth_account
    print("✓ Hyperliquid SDK importado\n")
except ImportError as e:
    print(f"❌ Hyperliquid SDK não instalado: {e}")
    print("   Instala com: pip install hyperliquid-python-sdk")
    sys.exit(1)

BASE_URL = "https://api.hyperliquid-testnet.xyz"

# ── 1. Ligação via Info (só leitura — não faz trades) ────────────────
print("🔗 Ligando ao Hyperliquid TESTNET (Info)...\n")
try:
    info = Info(base_url=BASE_URL, skip_ws=True)
    print("✅ Conectado ao TESTNET\n")
except Exception as e:
    import traceback
    print(f"❌ Erro ao conectar Info: {e}")
    traceback.print_exc()
    sys.exit(1)

# ── 2. Saldo ─────────────────────────────────────────────────────────
print("📊 Verificando saldo...\n")
try:
    user_state = info.user_state(wallet)
    margin_summary = user_state.get("marginSummary", {})
    account_value = float(margin_summary.get("accountValue", 0))
    withdrawable   = float(user_state.get("withdrawable", 0))

    if account_value > 0:
        print(f"💰 Account Value: ${account_value:,.2f}")
        print(f"💵 Withdrawable:  ${withdrawable:,.2f}\n")
    else:
        print("⚠️  Saldo zero — ainda não recebeste testnet funds?")
        print("   Pede em: https://hyperliquid.xyz/testnet\n")
except Exception as e:
    print(f"❌ Erro ao fetchar saldo: {e}\n")

# ── 3. Posições abertas ───────────────────────────────────────────────
print("📈 Posições abertas...\n")
try:
    user_state = info.user_state(wallet)
    positions = [
        p for p in user_state.get("assetPositions", [])
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
    orders = info.open_orders(wallet)
    if orders:
        print(f"✓ {len(orders)} ordem(ns) abertas:")
        for o in orders:
            print(f"  {o}")
    else:
        print("✓ Sem ordens abertas")
except Exception as e:
    print(f"❌ Erro ao fetchar ordens: {e}\n")

# ── 5. Mercado ────────────────────────────────────────────────────────
print("\n🧪 Mercado disponível...\n")
try:
    meta = info.meta()
    coins = meta.get("universe", [])
    print(f"✓ {len(coins)} pares disponíveis na testnet")
    for c in coins[:5]:
        print(f"  {c.get('name')}")
    print("  ...")
    print("\n✅ TESTNET ACESSÍVEL E FUNCIONAL!")
except Exception as e:
    print(f"❌ Erro ao fetchar mercado: {e}")

# ── 6. Teste do Exchange (para trades) ────────────────────────────────
print("\n🔑 Testando Exchange (necessário para ordens)...\n")
try:
    from hyperliquid.exchange import Exchange
    account = eth_account.Account.from_key(private_key)
    exchange = Exchange(
        wallet=account,
        base_url=BASE_URL,
        account_address=wallet,
    )
    print("✅ Exchange inicializado — pronto para fazer ordens!\n")
except Exception as e:
    print(f"⚠️  Exchange não inicializado: {e}")
    print("   (Info funciona — só ordens é que falhariam)\n")

print("=" * 60)
print("PRÓXIMOS PASSOS:")
print("=" * 60)
print("1. Se viste o saldo: Podes fazer trading na testnet ✓")
print("2. Se saldo = 0: Pede testnet funds em:")
print("   https://app.hyperliquid-testnet.xyz/drip")
print("3. Para correr o bot na testnet: HL_MODE=test no .env")
print("=" * 60)
