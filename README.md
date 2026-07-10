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
- Default OpenRouter model: `openai/gpt-oss-20b`

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

The Phase 1 foundation is fully wired into the later phases now, so the queue chain no longer stops at placeholder downstream tasks.

## Phase 2 Status

Phase 2 now adds:

- canonical parsing for `txt`, `md`, `html`, `pdf`, and `docx`
- Tesseract OCR for image files and scanned PDFs
- artifact persistence for `parsed.json` and `chunks.json` in RustFS
- PostgreSQL-backed chunk storage
- PGVector-backed embedding storage with real BGE-M3 embeddings
- retrieval service reading real chunks and embeddings from Postgres

Current limits in this phase:

- OCR quality depends on Tesseract language packs and source image quality
- BGE-M3 is now the default embedding provider, which increases image size and startup time because the model runtime must be available inside the worker and retrieval containers
- graph extraction and Neo4j upsert remain Phase 3 work

## Runtime Hardening

- `retrieval-service`, `worker`, and `worker-runner` now share a Hugging Face cache volume at `/opt/hf-cache`
- Docker can preload the BGE-M3 model during build through `PRELOAD_BGE_M3=true`
- OCR health endpoint: `GET /health/ocr` on `document-service` and `worker`
- Embedding health endpoint: `GET /health/embedding` on `retrieval-service` and `worker`

## Phase 3 Status

Phase 3 now adds:

- OpenRouter-backed entity and relation extraction using `openai/gpt-oss-20b`
- extraction persistence in PostgreSQL and `chunk-extractions.json` artifact storage in RustFS
- Neo4j upsert for `Document`, `Entity`, `MENTIONED_IN`, and `RELATED_TO`
- graph-service neighbors and document entities backed by real Neo4j queries

Current limits in this phase:

- graph retrieval is not merged into hybrid retrieval yet; that remains Phase 4
- answer generation in `llm-orchestrator` is still a placeholder response path
- extraction quality depends on OpenRouter connectivity, the chosen provider behind `gpt-oss-20b`, and your domain prompt tuning

## Notes

- This repo is a strong starter scaffold, not the full Graph RAG implementation.
- The code already defines the service boundaries, request contracts and adapter seams for OpenRouter, RustFS, PGVector and Neo4j.
- Phase 1 has replaced in-memory ingest metadata with PostgreSQL-backed persistence.
- Phase 2 and Phase 3 are now scaffolded in code, but still need full runtime validation and quality tuning.
