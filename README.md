# Enterprise Chatbot Graph RAG

Production-oriented scaffold for an enterprise Graph RAG platform with:

- `apps/web`: Next.js 15 dashboard UI
- `services/api-gateway`: orchestration entrypoint for frontend clients
- `services/document-service`: document ingest metadata API
- `services/retrieval-service`: retrieval planning and hybrid search stub
- `services/graph-service`: graph exploration API stub
- `services/llm-orchestrator`: OpenRouter-ready response orchestration
- `services/worker`: worker control API and Celery task definitions
- `packages/python/enterprise_ai_core`: shared Python settings, schemas and utilities

## Stack

- Frontend: Next.js 15, React 19, TypeScript
- Backend: FastAPI, Python 3.12
- Queue: RabbitMQ
- Cache: Redis
- Vector store: PostgreSQL + PGVector (compose ships vanilla Postgres scaffold)
- Graph: Neo4j
- Storage: RustFS
- LLM gateway: OpenRouter

## Quick Start

1. Copy `.env.example` to `.env`.
2. Start the stack:

```bash
docker compose up --build
```

3. Open:

- Web UI: `http://localhost:3000`
- API Gateway: `http://localhost:8000/docs`
- Document Service: `http://localhost:8001/docs`
- Retrieval Service: `http://localhost:8002/docs`
- Graph Service: `http://localhost:8003/docs`
- LLM Orchestrator: `http://localhost:8004/docs`
- Worker API: `http://localhost:8005/docs`

## Phase 1 Status

Phase 1 now includes:

- real multipart upload entrypoint through the gateway
- raw file persistence into RustFS
- PostgreSQL-backed metadata tables for documents, versions, artifacts and processing jobs
- Celery + RabbitMQ job chaining for `document.parse -> document.chunk -> document.embed -> graph.extract -> graph.upsert`
- worker control API for job inspection

The downstream pipeline stages are still placeholder tasks in this phase. They move job state through a real queue, but they do not yet parse content, embed chunks, extract entities or update Neo4j.

## Notes

- This repo is a strong starter scaffold, not the full Graph RAG implementation.
- The code already defines the service boundaries, request contracts and adapter seams for OpenRouter, RustFS, PGVector and Neo4j.
- Phase 1 has replaced in-memory ingest metadata with PostgreSQL-backed persistence.
- Phase 2 should implement parsing, OCR, canonicalization, chunking and embeddings.
