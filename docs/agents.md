# Agents — Catálogo de Agentes ClawCapital

## Visão Geral
Cada agente tem uma responsabilidade única e bem delimitada. A comunicação entre agentes é feita via mensagens estruturadas (JSON) com campos: `from`, `to`, `type`, `payload`, `timestamp`, `confidence`.

---

## Agentes Ativos

### 1. Orquestrador (`orchestrator`)
- **Função:** Agenda ciclos, distribui tarefas, consolida outputs dos agentes analíticos, decide se há consenso para acionar o agente de execução.
- **Inputs:** heartbeat, outputs de todos os agentes
- **Outputs:** decisão de ciclo (buy / sell / hold / halt)

### 2. Agregador de Notícias (`news-aggregator`)
- **Função:** Recolhe e processa notícias financeiras, comunicados macro, eventos de calendário económico.
- **Fontes:** a definir (RSS, APIs de notícias, scraping)
- **Output:** score de sentimento por ativo/setor + eventos críticos detetados
- **Pasta:** `agregador-noticias/`

### 3. Analista de Mercado (`market-analyst`)
- **Função:** Processa dados OHLCV, calcula indicadores técnicos, identifica padrões e regimes de mercado.
- **Inputs:** dados de `dados-mercado/`
- **Output:** sinal técnico por ativo (bullish / bearish / neutral) + nível de confiança

### 4. Gestor de Risco (`risk-manager`)
<br>
- **Função:** Valida todas as decisões antes de execução. Calcula position sizing, verifica drawdown atual, correlações de portfólio, exposição máxima.
- **Regras:** definidas em `gestão-risco/`
- **Veto:** pode bloquear qualquer ordem independentemente de outros agentes

### 5. Agente de Execução (`executor`)
- **Função:** Submete ordens ao broker/exchange, monitoriza fills, gere stop-loss e take-profit.
- **Só opera** após validação do `risk-manager`
- **Regista** todas as execuções em `memory/`

### 6. Agente de Memória (`memory-agent`)
- **Função:** Persiste contexto de sessão, padrões aprendidos, histórico de trades, erros passados.
- **Pasta:** `memory/`

---

## Agentes Planeados (futuro)
- `sentiment-agent` — análise de sentimento em redes sociais / fóruns
- `macro-agent` — monitorização de dados macroeconómicos e bancos centrais
- `backtest-agent` — validação de estratégias em dados históricos
