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
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    import eth_account
    print("✓ Hyperliquid SDK importado\n")
except ImportError as e:
    print(f"❌ Hyperliquid SDK não instalado: {e}")
    print("   Instala com: pip install hyperliquid-python-sdk")
    sys.exit(1)

# Connect to TESTNET
print("🔗 Ligando ao Hyperliquid TESTNET...\n")
try:
    account = eth_account.Account.from_key(private_key)

    exchange = Exchange(
        wallet=account,
        base_url="https://api.hyperliquid-testnet.xyz",
        account_address=wallet,
    )
    info = Info(
        base_url="https://api.hyperliquid-testnet.xyz",
        skip_ws=True
    )
    print("✅ Conectado ao TESTNET\n")
except Exception as e:
    import traceback
    print(f"❌ Erro ao conectar: {e}")
    traceback.print_exc()
    sys.exit(1)

# Check balance
print("📊 Verificando saldo...\n")
try:
    user_state = info.user_state(wallet)
    if user_state and "balanceState" in user_state:
        balance_state = user_state["balanceState"]
        total_usd = float(balance_state.get("accountValue", 0))
        print(f"💰 Saldo total: ${total_usd:,.2f}")
        print(f"   Wallet: {wallet}\n")
    else:
        print("⚠️  Nenhum saldo encontrado. Recebes testnet funds?")
except Exception as e:
    print(f"❌ Erro ao fetchar saldo: {e}\n")

# Check open positions
print("📈 Posições abertas...\n")
try:
    positions = info.open_orders(wallet)
    if positions:
        print(f"✓ {len(positions)} ordens abertas:")
        for pos in positions:
            print(f"  - {pos}")
    else:
        print("✓ Sem posições abertas (normal para novo trader)")
except Exception as e:
    print(f"❌ Erro ao fetchar posições: {e}\n")

# Try a simple read operation
print("\n🧪 Teste: fetchar informações do mercado...\n")
try:
    # Get metadata
    meta = info.meta()
    if meta:
        coins = meta.get("universe", [])
        print(f"✓ Mercado ativo com {len(coins)} pares")
        btc = next((c for c in coins if c.get("name") == "BTC"), None)
        if btc:
            print(f"  Exemplo: BTC token ID {btc.get('index')}")
    print("\n✅ TESTNET ACESSÍVEL E FUNCIONAL!")
except Exception as e:
    print(f"❌ Erro ao fetchar metadata: {e}")

print("\n" + "="*60)
print("PRÓXIMOS PASSOS:")
print("="*60)
print("1. Se viste o saldo: Podes fazer trading na testnet ✓")
print("2. Se não viste saldo: Pede testnet funds em:")
print("   https://hyperliquid.xyz/testnet")
print("3. Para correr o bot na testnet: HL_MODE=test")
print("="*60)
