# Heartbeat — Sistema de Saúde ClawCapital

## Propósito
O heartbeat é o mecanismo de auto-monitorização do sistema. Corre em intervalos regulares e verifica se todos os componentes estão operacionais antes de permitir qualquer ciclo de análise ou execução.

## Frequência
- Heartbeat interno: a definir (ex: a cada 60 segundos)
- Health report completo: a definir (ex: início de cada sessão de mercado)

## Verificações por Ciclo

### Conectividade
- [ ] Ligação ao broker/exchange ativa
- [ ] APIs de dados de mercado respondendo
- [ ] APIs de notícias respondendo
- [ ] Canal de notificação ao utilizador ativo

### Estado dos Agentes
- [ ] Orquestrador: ativo
- [ ] Agregador de notícias: ativo
- [ ] Analista de mercado: ativo
- [ ] Gestor de risco: ativo
- [ ] Agente de execução: ativo (apenas em modo live)

### Estado do Portfólio
- [ ] Posições abertas sincronizadas com broker
- [ ] Drawdown atual dentro dos limites
- [ ] Saldo disponível suficiente para operar

### Integridade de Dados
- [ ] Dados de mercado atualizados (sem gaps)
- [ ] Memória acessível e consistente

## Comportamento em Falha
| Falha | Ação |
|-------|------|
| Broker desconectado | Suspender execução, alertar utilizador |
| Dados de mercado em falta | Suspender análise técnica, continuar com notícias |
| Drawdown > limite | Modo halt — bloquear novas ordens, alertar |
| Agente crítico offline | Suspender ciclo, tentar reiniciar, alertar |

## Log
Cada heartbeat regista resultado em `memory/heartbeat-log.json`.
