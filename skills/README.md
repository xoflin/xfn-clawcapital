# Skills

Capacidades modulares reutilizáveis partilhadas entre os agentes do ClawCapital.
Cada skill é uma unidade funcional pura (sem estado, sem logging de ciclo) que pode ser
invocada por qualquer agente ou testada de forma independente.

## Estrutura

```
skills/
├── data_fetchers/
│   ├── cryptopanic.py     # fetch_headlines() — CryptoPanic API
│   └── coingecko.py       # CoinGeckoClient — preços, OHLC, batch snapshots
│
├── sentiment_analysis/
│   └── gemini_sentiment.py  # analyse() — análise LLM via Gemini Flash
│
├── technical_analysis/
│   ├── sma.py             # calculate(), calculate_many(), pct_diff()
│   └── signal.py          # derive() — Bullish / Neutro / Bearish
│
└── position_sizing/
    ├── kelly.py            # full_kelly(), fractional_kelly()
    └── fixed_fractional.py # risk_amount(), position_size_from_risk()
```

## Quem usa cada skill

| Skill | Usado por |
|---|---|
| `data_fetchers.cryptopanic` | `agregador_noticias` |
| `data_fetchers.coingecko` | `dados_mercado` |
| `sentiment_analysis.gemini_sentiment` | `agregador_noticias` |
| `technical_analysis.sma` | `dados_mercado` |
| `technical_analysis.signal` | `dados_mercado` |
| `position_sizing.kelly` | `gestão_risco` |
| `position_sizing.fixed_fractional` | `gestão_risco` |

## Convenção

- **Sem estado** — funções puras ou clientes HTTP sem cache interno.
- **Sem side-effects de logging** — os agentes é que fazem `print()`.
- **Input/Output** documentados no docstring de cada módulo.
- **Testáveis de forma independente** — sem dependências cruzadas entre skills.
