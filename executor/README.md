# Executor — Agente de Execução

Submete ordens ao exchange e gere posições abertas. Suporta **paper trading** (simulação) e **live trading** via [CCXT](https://github.com/ccxt/ccxt) (100+ exchanges).

## Ficheiros
- `executor.py` — implementação principal (`ExecutionAgent`)
- `requirements.txt` — dependências Python (ccxt)

## Instalação (apenas para live trading)
```bash
pip install ccxt
```

## Modos de Operação

### Paper Trading (default — sem risco)
```python
from executor.executor import ExecutionAgent, ExecutionMode

agent = ExecutionAgent(mode=ExecutionMode.PAPER)
```
Ordens são simuladas com fill imediato ao preço de entrada. Tudo registado em `memory/trades-history.json`.

### Live Trading
```python
agent = ExecutionAgent(
    mode=ExecutionMode.LIVE,
    exchange_id="binance",         # qualquer exchange CCXT
    api_key=os.environ["EXCHANGE_API_KEY"],
    api_secret=os.environ["EXCHANGE_API_SECRET"],
    sandbox=True,                  # True = testnet, False = real
)
```

## Integração com Orquestrador
```python
# Processar decisões de um ciclo completo
orders = agent.process_cycle_decisions(cycle_output)
```
Executa apenas ordens com `approved=True` e direção `BUY` ou `SELL`. Ignora `HOLD` e posições já abertas.

## Output — trades-history.json
```json
{
  "id": "a3f2c1b0",
  "ticker": "BTC",
  "side": "buy",
  "order_type": "market",
  "size_units": 0.00301,
  "size_usd": 195.50,
  "entry_price": 65000,
  "stop_loss_price": 63050,
  "take_profit_price": 68900,
  "status": "filled",
  "filled_price": 65000,
  "mode": "paper"
}
```

## Logging
| Ficheiro | Conteúdo |
|----------|----------|
| `memory/trades-history.json` | Todas as ordens abertas |
| `memory/closed-trades.json` | Trades fechados com PnL |

## Teste Rápido
```bash
python executor/executor.py
```
