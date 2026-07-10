# Architecture Overview

## Monorepo Layout

```text
apps/
  web/                  Next.js operator UI
services/
  api-gateway/          Client-facing orchestration layer
  document-service/     Ingest metadata and upload lifecycle
  retrieval-service/    Hybrid retrieval planner
  graph-service/        Graph exploration and topology API
  llm-orchestrator/     OpenRouter-ready answer generation
  worker/               Async pipeline worker
packages/
  python/
    enterprise_ai_core/ Shared settings, schemas, utilities
infra/
  docker/               Dockerfiles
docs/                   Architecture notes
```

## Delivery Philosophy

- Start with clear service contracts and thin implementations.
- Keep infrastructure choices explicit in config from day one.
- Avoid fake production claims: persistence adapters are stubbed where implementation work is still needed.
- Make every boundary observable and replaceable.

