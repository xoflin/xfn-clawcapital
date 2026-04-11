# OpenClaw Skill: ClawCapital Manager

## Descrição
Gere o ClawCapital — bot autónomo de trading crypto. Inicia, para, monitoriza
e analisa performance histórica.

## Comandos

| Trigger (chat) | Comando shell | O que faz |
|----------------|---------------|-----------|
| "claw start" | `./clawctl.sh start` | Inicia o smart scheduler (ciclos adaptados ao mercado) |
| "claw stop" | `./clawctl.sh stop` | Para o bot |
| "claw restart" | `./clawctl.sh restart` | Reinicia o bot |
| "claw status" | `./clawctl.sh status` | Mostra se está a correr + últimas linhas de log |
| "claw run" | `./clawctl.sh once` | Corre um único ciclo (debug) |
| "claw learn" | `./clawctl.sh learn` | Analisa trades passados e mostra o que aprendeu |
| "claw report" | `./clawctl.sh report` | Relatório completo: status + learning + quotas |
| "claw log" | `./clawctl.sh log` | Mostra log em tempo real |

## Directório de trabalho
```
/caminho/para/xfn-clawcapital/
```

## Schedule automático
O smart scheduler (`scheduler.py`) ajusta a frequência dos ciclos ao mercado:

| Hora UTC | Hora PT | Sessão | Intervalo |
|----------|---------|--------|-----------|
| 13:00-16:00 | 14:00-17:00 | US open (pico) | 1h |
| 16:00-21:00 | 17:00-22:00 | US session | 1.5h |
| 21:00-23:00 | 22:00-00:00 | US close | 1h |
| 07:00-13:00 | 08:00-14:00 | Europa | 2h |
| 23:00-07:00 | 00:00-08:00 | Ásia / noite | 4h |

## Aprendizagem
O bot aprende automaticamente:
1. Cada trade que fecha dispara `trade_analyzer.analyze()`
2. O resultado é gravado em `memory/lessons.json`
3. No ciclo seguinte, os agentes (Investigator + Manager) recebem:
   - Win rate por ticker e por direcção
   - Padrões detectados (ex: "BUY underperforms at conf < 0.55")
   - Calibração de confiança vs resultado real
4. Os agentes ajustam convicções com base nesta informação

## Ficheiros importantes
| Ficheiro | Função |
|----------|--------|
| `memory/lessons.json` | Aprendizagem acumulada |
| `memory/closed-trades.json` | Histórico de trades com PnL |
| `memory/cycles-log.json` | Últimos 500 ciclos |
| `logs/clawcapital.log` | Log do processo |
| `.env` | Configuração (API keys, parâmetros de risco) |

## Comportamento esperado
- O OpenClaw deve executar `claw start` quando o utilizador pedir
- Monitorizar com `claw status` periodicamente
- Se o processo cair, notificar e oferecer `claw restart`
- Quando o utilizador perguntar "como está o bot?", executar `claw report`
- Quando perguntar "o que aprendeu?", executar `claw learn`
