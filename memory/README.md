# Memory

Armazenamento persistente do sistema ClawCapital. Contém contexto de sessão, histórico de trades, padrões aprendidos e logs operacionais.

## Estrutura Esperada
```
memory/
├── heartbeat-log.json       # Logs de saúde do sistema
├── trades-history.json      # Histórico de todas as ordens executadas
├── session-context.json     # Contexto da sessão atual
├── learned-patterns/        # Padrões identificados e validados
└── errors-log.json          # Erros e exceções registados
```

> Ficheiros gerados automaticamente pelos agentes em runtime.
