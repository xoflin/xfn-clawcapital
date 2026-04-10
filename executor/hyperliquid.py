"""
Executor: Hyperliquid L1
Submete ordens de perpetuais ao Hyperliquid via SDK oficial.

Vantagens arquitecturais do Hyperliquid:
  - Sem mempool público → sem frontrunning por bots MEV
  - L1 dedicado a trading → latência < 1s
  - Perpetuais com até 50x leverage (usamos 1x por padrão — sem alavancagem)

Modos:
  PAPER — simula fills localmente, sem ligação à rede
  LIVE  — ordem real assinada com chave privada Ethereum → Hyperliquid mainnet
  TEST  — usa testnet Hyperliquid (app.hyperliquid-testnet.xyz)

Dependência:
  pip install hyperliquid-python-sdk

Variáveis de ambiente (modo LIVE/TEST):
  HL_WALLET_ADDRESS   — endereço Ethereum (0x...)
  HL_PRIVATE_KEY      — chave privada (nunca commitar)
  HL_AGENT_KEY        — chave de agente opcional (sub-account para isolar risco)

Referência SDK:
  https://github.com/hyperliquid-dex/hyperliquid-python-sdk
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

MEMORY_DIR = Path(__file__).parent.parent / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Enums e constantes
# ------------------------------------------------------------------

class HLMode(Enum):
    PAPER = "paper"   # Simulação local
    TEST  = "test"    # Testnet Hyperliquid
    LIVE  = "live"    # Mainnet Hyperliquid


HL_MAINNET_URL = "https://api.hyperliquid.xyz"
HL_TESTNET_URL = "https://api.hyperliquid-testnet.xyz"

# Hyperliquid usa nomes exactos para os pares perpetuais
# Adicionar conforme necessário
HL_COIN_MAP: dict[str, str] = {
    "BTC":  "BTC",
    "ETH":  "ETH",
    "SOL":  "SOL",
    "ARB":  "ARB",
    "OP":   "OP",
    "AVAX": "AVAX",
    "BNB":  "BNB",
    "MATIC": "MATIC",
    "DOGE": "DOGE",
    "LINK": "LINK",
}


# ------------------------------------------------------------------
# Estrutura de ordem
# ------------------------------------------------------------------

@dataclass
class HLOrder:
    id: str
    ticker: str
    coin: str                          # Nome Hyperliquid (ex: "BTC")
    side: str                          # "buy" | "sell"
    size_usd: float
    size_units: float                  # Quantidade em moeda base
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    leverage: int = 1                  # 1 = sem alavancagem
    mode: str = HLMode.PAPER.value
    status: str = "pending"
    filled_price: float | None = None
    filled_at: str | None = None
    hl_order_id: int | None = None     # OID devolvido pelo Hyperliquid
    sl_order_id: int | None = None
    tp_order_id: int | None = None
    notes: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------
# Executor Hyperliquid
# ------------------------------------------------------------------

class HyperliquidExecutor:
    """
    Submete ordens de perpetuais ao Hyperliquid L1.

    Args:
        mode:            PAPER (simulação), TEST (testnet) ou LIVE (mainnet).
        wallet_address:  Endereço Ethereum (obrigatório em TEST/LIVE).
        private_key:     Chave privada para assinar ordens (obrigatório em TEST/LIVE).
        agent_key:       Chave de agente opcional (sub-account isolada).
        leverage:        Alavancagem por defeito (default 1 = sem alavancagem).
        slippage_pct:    Tolerância de slippage para ordens a mercado (default 0.1%).
    """

    def __init__(
        self,
        mode: HLMode = HLMode.PAPER,
        wallet_address: str | None = None,
        private_key: str | None = None,
        agent_key: str | None = None,
        leverage: int = 1,
        slippage_pct: float = 0.1,
    ):
        self.mode = mode
        self.wallet_address = wallet_address
        self.leverage = leverage
        self.slippage_pct = slippage_pct
        self._exchange = None
        self._info = None
        self._open_positions: dict[str, HLOrder] = self._load_open_positions()

        if mode in (HLMode.TEST, HLMode.LIVE):
            if not wallet_address or not private_key:
                raise ValueError(
                    "wallet_address e private_key são obrigatórios em modo TEST/LIVE."
                )
            self._exchange, self._info = self._init_hl(
                wallet_address=wallet_address,
                private_key=private_key,
                agent_key=agent_key,
                testnet=(mode == HLMode.TEST),
            )

    # ------------------------------------------------------------------
    # Inicialização SDK Hyperliquid
    # ------------------------------------------------------------------

    @staticmethod
    def _init_hl(
        wallet_address: str,
        private_key: str,
        agent_key: str | None,
        testnet: bool,
    ):
        try:
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            import eth_account
        except ImportError:
            raise ImportError(
                "SDK Hyperliquid não instalado. Execute: pip install hyperliquid-python-sdk"
            )

        base_url = HL_TESTNET_URL if testnet else HL_MAINNET_URL

        # Construir wallet a partir da chave privada
        key_to_use = agent_key if agent_key else private_key
        wallet = eth_account.Account.from_key(key_to_use)

        # Obter meta e spot_meta via HTTP para evitar bug do SDK na testnet
        # (a testnet tem pares spot com índices de tokens fora do intervalo)
        import requests as _req
        meta_resp      = _req.post(f"{base_url}/info", json={"type": "meta"}, timeout=10).json()
        spot_meta_resp = _req.post(f"{base_url}/info", json={"type": "spotMeta"}, timeout=10).json()
        tokens = spot_meta_resp.get("tokens", [])
        valid_universe = [
            s for s in spot_meta_resp.get("universe", [])
            if len(s.get("tokens", [])) >= 2 and max(s["tokens"]) < len(tokens)
        ]
        spot_meta_fixed = {"universe": valid_universe, "tokens": tokens}

        # Exchange espera: wallet, base_url, meta, account_address, spot_meta
        exchange = Exchange(
            wallet=wallet,
            base_url=base_url,
            account_address=wallet_address,
            meta=meta_resp,
            spot_meta=spot_meta_fixed,
        )
        info = Info(base_url=base_url, skip_ws=True, meta=meta_resp, spot_meta=spot_meta_fixed)

        env = "TESTNET" if testnet else "MAINNET"
        print(f"[HL Executor] Ligado ao Hyperliquid {env} — wallet: {wallet_address[:10]}...")
        return exchange, info

    # ------------------------------------------------------------------
    # Position persistence across restarts
    # ------------------------------------------------------------------

    def _load_open_positions(self) -> dict[str, HLOrder]:
        """
        Restores open positions from disk on startup.
        Cross-references trades-history.json against closed-trades.json
        to determine which fills are still open.
        """
        trades_path = MEMORY_DIR / "trades-history.json"
        closed_path = MEMORY_DIR / "closed-trades.json"

        if not trades_path.exists():
            return {}

        try:
            all_trades: list[dict] = json.loads(trades_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        # Build set of closed order IDs
        closed_ids: set[str] = set()
        if closed_path.exists():
            try:
                closed = json.loads(closed_path.read_text(encoding="utf-8"))
                closed_ids = {c["order_id"] for c in closed if c.get("order_id")}
            except Exception:
                pass

        open_positions: dict[str, HLOrder] = {}
        fields = HLOrder.__dataclass_fields__.keys()
        for trade in all_trades:
            if trade.get("status") != "filled":
                continue
            if trade.get("id") in closed_ids:
                continue
            ticker = trade.get("ticker", "")
            if not ticker:
                continue
            try:
                order = HLOrder(**{k: v for k, v in trade.items() if k in fields})
                open_positions[ticker] = order
            except Exception:
                continue

        if open_positions:
            print(f"[HL Executor] Restored {len(open_positions)} open position(s): "
                  f"{list(open_positions.keys())}")
        return open_positions

    # ------------------------------------------------------------------
    # Normalização de coin
    # ------------------------------------------------------------------

    def _coin(self, ticker: str) -> str:
        """Converte ticker interno para nome Hyperliquid."""
        t = ticker.upper()
        return HL_COIN_MAP.get(t, t)  # fallback para o próprio ticker

    # ------------------------------------------------------------------
    # Submissão de ordem
    # ------------------------------------------------------------------

    def submit_order(
        self,
        ticker: str,
        side: str,                     # "buy" | "sell"
        size_usd: float,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        notes: str = "",
    ) -> HLOrder:
        """
        Cria e submete uma ordem de perpetual no Hyperliquid.

        Em PAPER: fill simulado imediato.
        Em TEST/LIVE: assina e envia ao L1 via SDK.

        Args:
            ticker:            Ticker do ativo (ex: "BTC").
            side:              "buy" ou "sell".
            size_usd:          Valor da posição em USD.
            entry_price:       Preço de entrada (usado para calcular size_units).
            stop_loss_price:   Preço de stop loss.
            take_profit_price: Preço de take profit.
            notes:             Notas adicionais para o registo.

        Returns:
            HLOrder com estado preenchido.
        """
        coin = self._coin(ticker)
        size_units = round(size_usd / entry_price, 6)

        order = HLOrder(
            id=str(uuid.uuid4())[:8],
            ticker=ticker.upper(),
            coin=coin,
            side=side.lower(),
            size_usd=size_usd,
            size_units=size_units,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            leverage=self.leverage,
            mode=self.mode.value,
            notes=notes,
        )

        print(f"\n[HL Executor] Nova ordem #{order.id}")
        print(f"  {side.upper()} {size_units:.6f} {ticker} "
              f"@ ${entry_price:,.4f} ({self.mode.value})")
        print(f"  SL: ${stop_loss_price:,.4f} | TP: ${take_profit_price:,.4f}")

        if self.mode == HLMode.PAPER:
            self._fill_paper(order)
        else:
            self._fill_live(order)

        self._open_positions[ticker.upper()] = order
        self._log_order(order)
        return order

    # ------------------------------------------------------------------
    # Paper fill
    # ------------------------------------------------------------------

    def _fill_paper(self, order: HLOrder) -> None:
        order.filled_price = order.entry_price
        order.filled_at = datetime.now(timezone.utc).isoformat()
        order.status = "filled"
        order.hl_order_id = -1
        order.sl_order_id = -2
        order.tp_order_id = -3
        print(f"  [PAPER] Filled @ ${order.filled_price:,.4f}")

    # ------------------------------------------------------------------
    # Live fill (Hyperliquid SDK)
    # ------------------------------------------------------------------

    def _fill_live(self, order: HLOrder) -> None:
        """
        Submete três ordens ao Hyperliquid:
          1. Ordem principal a mercado (IOC — Immediate Or Cancel)
          2. Stop Loss trigger order
          3. Take Profit trigger order
        """
        is_buy = order.side == "buy"

        # 1. Ordem principal (market via IOC limit com slippage)
        slippage = self.slippage_pct / 100
        if is_buy:
            limit_px = round(order.entry_price * (1 + slippage), 6)
        else:
            limit_px = round(order.entry_price * (1 - slippage), 6)

        try:
            result = self._exchange.order(
                coin=order.coin,
                is_buy=is_buy,
                sz=order.size_units,
                limit_px=limit_px,
                order_type={"limit": {"tif": "Ioc"}},  # IOC = market
                reduce_only=False,
            )
            self._check_hl_response(result, "ordem principal")
            status_data = result.get("response", {}).get("data", {})
            statuses = status_data.get("statuses", [{}])
            filled = statuses[0] if statuses else {}
            order.hl_order_id = filled.get("resting", {}).get("oid") or filled.get("filled", {}).get("oid")
            order.filled_price = float(filled.get("filled", {}).get("avgPx", order.entry_price) or order.entry_price)
            order.filled_at = datetime.now(timezone.utc).isoformat()
            order.status = "filled"
            print(f"  [LIVE] Filled @ ${order.filled_price:,.4f} | OID: {order.hl_order_id}")
        except Exception as e:
            order.status = "rejected"
            order.notes += f" | Erro ordem principal: {e}"
            print(f"  [LIVE] ERRO na ordem principal: {e}")
            raise

        # 2. Stop Loss (trigger order — executa a mercado quando atingido)
        try:
            sl_result = self._exchange.order(
                coin=order.coin,
                is_buy=not is_buy,       # Inverso: fecha posição
                sz=order.size_units,
                limit_px=order.stop_loss_price,
                order_type={
                    "trigger": {
                        "triggerPx": order.stop_loss_price,
                        "isMarket": True,
                        "tpsl": "sl",
                    }
                },
                reduce_only=True,
            )
            self._check_hl_response(sl_result, "stop loss")
            sl_statuses = sl_result.get("response", {}).get("data", {}).get("statuses", [{}])
            order.sl_order_id = sl_statuses[0].get("resting", {}).get("oid")
            print(f"  [LIVE] SL colocado @ ${order.stop_loss_price:,.4f} | OID: {order.sl_order_id}")
        except Exception as e:
            order.notes += f" | SL manual necessário @ ${order.stop_loss_price:.4f}: {e}"
            print(f"  [LIVE] AVISO: SL não colocado — {e}")

        # 3. Take Profit (trigger order)
        try:
            tp_result = self._exchange.order(
                coin=order.coin,
                is_buy=not is_buy,
                sz=order.size_units,
                limit_px=order.take_profit_price,
                order_type={
                    "trigger": {
                        "triggerPx": order.take_profit_price,
                        "isMarket": True,
                        "tpsl": "tp",
                    }
                },
                reduce_only=True,
            )
            self._check_hl_response(tp_result, "take profit")
            tp_statuses = tp_result.get("response", {}).get("data", {}).get("statuses", [{}])
            order.tp_order_id = tp_statuses[0].get("resting", {}).get("oid")
            print(f"  [LIVE] TP colocado @ ${order.take_profit_price:,.4f} | OID: {order.tp_order_id}")
        except Exception as e:
            order.notes += f" | TP manual necessário @ ${order.take_profit_price:.4f}: {e}"
            print(f"  [LIVE] AVISO: TP não colocado — {e}")

    # ------------------------------------------------------------------
    # Fechar posição
    # ------------------------------------------------------------------

    def close_position(self, ticker: str, current_price: float) -> dict | None:
        """
        Fecha posição aberta a mercado.
        Em LIVE: cancela SL/TP pendentes e submete ordem de fecho.
        """
        ticker = ticker.upper()
        if ticker not in self._open_positions:
            print(f"[HL Executor] Sem posição aberta para {ticker}")
            return None

        original = self._open_positions[ticker]
        close_side = "sell" if original.side == "buy" else "buy"
        coin = original.coin

        print(f"[HL Executor] A fechar {ticker} @ ${current_price:,.4f}")

        if self.mode in (HLMode.TEST, HLMode.LIVE):
            # Cancelar SL e TP
            for oid in [original.sl_order_id, original.tp_order_id]:
                if oid and oid > 0:
                    try:
                        self._exchange.cancel(coin=coin, oid=oid)
                    except Exception:
                        pass

            # Ordem de fecho a mercado
            slippage = self.slippage_pct / 100
            is_buy = close_side == "buy"
            limit_px = round(
                current_price * (1 + slippage) if is_buy else current_price * (1 - slippage),
                6,
            )
            try:
                self._exchange.order(
                    coin=coin,
                    is_buy=is_buy,
                    sz=original.size_units,
                    limit_px=limit_px,
                    order_type={"limit": {"tif": "Ioc"}},
                    reduce_only=True,
                )
            except Exception as e:
                print(f"  [LIVE] ERRO ao fechar posição: {e}")

        # PnL
        entry = original.filled_price or original.entry_price
        if original.side == "buy":
            pnl_pct = ((current_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - current_price) / entry) * 100
        pnl_usd = original.size_usd * (pnl_pct / 100)

        close_record = {
            "order_id":   original.id,
            "ticker":     ticker,
            "side":       original.side,
            "open_price": entry,
            "close_price": current_price,
            "size_usd":   original.size_usd,
            "pnl_usd":    round(pnl_usd, 2),
            "pnl_pct":    round(pnl_pct, 4),
            "opened_at":  original.created_at,
            "closed_at":  datetime.now(timezone.utc).isoformat(),
            "mode":       self.mode.value,
        }
        print(f"  PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
        del self._open_positions[ticker]
        self._log_close(close_record)
        return close_record

    # ------------------------------------------------------------------
    # Saldo e posições via SDK
    # ------------------------------------------------------------------

    def get_account_state(self) -> dict:
        """
        Obtém saldo e posições abertas diretamente da chain.
        Só disponível em modo TEST/LIVE.
        """
        if self.mode == HLMode.PAPER:
            return {
                "mode": "paper",
                "open_positions": len(self._open_positions),
                "tickers": list(self._open_positions.keys()),
            }
        try:
            state = self._info.user_state(self.wallet_address)
            return {
                "mode":            self.mode.value,
                "margin_summary":  state.get("marginSummary", {}),
                "positions":       state.get("assetPositions", []),
                "open_positions":  len(self._open_positions),
            }
        except Exception as e:
            return {"error": str(e)}

    def get_open_positions(self) -> list[dict]:
        return [o.to_dict() for o in self._open_positions.values()]

    # ------------------------------------------------------------------
    # Ponto 1: Saldo real disponível na exchange
    # ------------------------------------------------------------------

    def get_available_balance(self) -> float | None:
        """
        Fetches the real withdrawable USDC balance from the exchange via HTTP.
        Returns None in PAPER mode (not applicable).

        Used to prevent the bot from sizing positions based on a configured
        capital that doesn't match the actual account balance.
        """
        if self.mode == HLMode.PAPER:
            return None
        if not self.wallet_address:
            return None

        base_url = HL_TESTNET_URL if self.mode == HLMode.TEST else HL_MAINNET_URL
        try:
            import requests as _req
            resp = _req.post(
                f"{base_url}/info",
                json={"type": "clearinghouseState", "user": self.wallet_address},
                timeout=10,
            )
            resp.raise_for_status()
            state = resp.json()
            withdrawable = float(state.get("withdrawable", 0))
            account_value = float(state.get("marginSummary", {}).get("accountValue", 0))
            return withdrawable if withdrawable > 0 else account_value
        except Exception as e:
            print(f"[HL Executor] WARNING — could not fetch balance: {e}")
            return None

    # ------------------------------------------------------------------
    # Ponto 3: Reconciliação de posições com a exchange
    # ------------------------------------------------------------------

    def reconcile_positions(self) -> list[dict]:
        """
        Compares local position state with real open positions on the exchange.
        Returns positions found on the exchange that are NOT in local state.

        Used to detect positions opened manually or from a previous session
        that weren't recorded in trades-history.json.
        """
        if self.mode == HLMode.PAPER:
            return []
        if not self.wallet_address:
            return []

        base_url = HL_TESTNET_URL if self.mode == HLMode.TEST else HL_MAINNET_URL
        try:
            import requests as _req
            resp = _req.post(
                f"{base_url}/info",
                json={"type": "clearinghouseState", "user": self.wallet_address},
                timeout=10,
            )
            resp.raise_for_status()
            state = resp.json()

            exchange_positions = [
                p["position"] for p in state.get("assetPositions", [])
                if float(p["position"].get("szi", 0)) != 0
            ]

            local_tickers = {t.upper() for t in self._open_positions.keys()}
            unknown = [
                p for p in exchange_positions
                if p.get("coin", "").upper() not in local_tickers
            ]
            return unknown
        except Exception as e:
            print(f"[HL Executor] WARNING — reconciliation failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_hl_response(response: dict, label: str) -> None:
        """Verifica se a resposta do Hyperliquid indica erro."""
        status = response.get("status", "")
        if status != "ok":
            err = response.get("response", response)
            raise RuntimeError(f"Hyperliquid rejeitou {label}: {err}")

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    @staticmethod
    def _append_log(filename: str, entry: dict) -> None:
        path = MEMORY_DIR / filename
        history: list = []
        if path.exists():
            try:
                history = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                history = []
        history.append(entry)
        if len(history) > 1000:
            history = history[-1000:]
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    def _log_order(self, order: HLOrder) -> None:
        self._append_log("trades-history.json", order.to_dict())

    def _log_close(self, record: dict) -> None:
        self._append_log("closed-trades.json", record)


# ------------------------------------------------------------------
# Execução direta (teste/debug — modo PAPER)
# ------------------------------------------------------------------

if __name__ == "__main__":
    executor = HyperliquidExecutor(mode=HLMode.PAPER)

    order = executor.submit_order(
        ticker="BTC",
        side="buy",
        size_usd=500.0,
        entry_price=65_000.0,
        stop_loss_price=63_050.0,
        take_profit_price=68_900.0,
        notes="Teste paper mode",
    )
    print(f"\nOrdem criada: {json.dumps(order.to_dict(), indent=2)}")

    state = executor.get_account_state()
    print(f"\nEstado da conta: {json.dumps(state, indent=2)}")

    close = executor.close_position("BTC", current_price=66_500.0)
    print(f"\nFecho: {json.dumps(close, indent=2)}")
