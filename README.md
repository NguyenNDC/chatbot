# Enterprise Chatbot Graph RAG

Monorepo cho mot he thong enterprise chatbot theo huong Graph RAG, gom luong ingest tai lieu, parse/chunk/embed, extract graph va generate cau tra loi co citation.

## Kien truc nhanh

- `apps/web`: giao dien Next.js cho upload tai lieu, theo doi job, hoi dap.
- `services/api-gateway`: entrypoint cho frontend, gom flow upload/query va fan-out sang cac service backend.
- `services/document-service`: nhan file, luu raw vao RustFS, quan ly document/version/job metadata trong PostgreSQL.
- `services/retrieval-service`: lap retrieval plan, hybrid retrieval tu PGVector + graph signals.
- `services/graph-service`: API tra cuu entity va quan he trong Neo4j.
- `services/llm-orchestrator`: chuan hoa policy tra loi, no-answer, refusal, clarification va goi OpenRouter.
- `services/worker`: API theo doi processing job.
- `services/worker/app/tasks.py`: Celery pipeline chay nen cho parse/chunk/embed/extract/upsert.
- `packages/python/enterprise_ai_core`: shared config, schema, DB model, queue, storage, parsing, embedding, prompting.

## Stack

- Frontend: Next.js 15, React 19, TypeScript
- Backend: FastAPI, Python 3.12
- Queue: RabbitMQ + Celery
- Cache: Redis
- Metadata + vector: PostgreSQL + PGVector
- Graph: Neo4j
- Object storage: RustFS
- LLM gateway: OpenRouter
- Docker dev mac dinh: `hash-1024`
- Full ML tuy chon: `BAAI/bge-m3`
- Lightweight semantic retrieval tuy chon: `intfloat/multilingual-e5-base`

## Cau truc dependency

Python dependencies da duoc tach theo nhom de tranh moi service phai keo ca OCR + ML stack:

- `requirements/base.txt`: FastAPI, SQLAlchemy, config, HTTP client
- `requirements/queue.txt`: Celery, Redis
- `requirements/storage.txt`: boto3
- `requirements/graph.txt`: neo4j
- `requirements/parsing.txt`: PDF, DOCX, PPTX, OCR, HTML parsing
- `requirements/ml.txt`: `FlagEmbedding`, `torch`, `transformers`, `sentencepiece`

Root `requirements.txt` van include toan bo nhom de ai can cai full local van dung duoc.

Mac dinh `docker compose` da duoc toi uu theo huong dev-lite:

- `retrieval-service` dung `hash` embedding, khong cai `torch/FlagEmbedding`
- `worker-runner` van giu parsing + OCR, nhung khong cai `ml.txt` neu khong can
- `document-service` khong con keo parsing/OCR stack

## Chay nhanh bang Docker

Day la cach nen dung de chay full stack.

### 1. Chuan bi env

Copy file mau:

```bash
cp .env.example .env
```

Neu chay bang Docker Compose, giu cac hostname noi bo nhu `postgres`, `redis`, `neo4j`, `rustfs`.

Bien quan trong nhat can set:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL_PRIMARY`
- `OPENROUTER_MODEL_FALLBACK`
- `OPENROUTER_MODEL_EXTRACTION`
- `GRAPH_EXTRACT_MAX_CONCURRENCY`

`GRAPH_EXTRACT_MAX_CONCURRENCY` cho phep `graph.extract` goi LLM song song theo nhieu chunk. Mac dinh la `6`; neu API key/rate limit cho phep va may con du tai, co the nang len `8-12`.

Tenant isolation hien tai duoc scope bang `tenant_id` o API layer. Khi goi cac endpoint documents/jobs/query tu client, can truyen dung tenant dang lam viec.

### 2. Build va chay toan bo he thong

Mac dinh lenh duoi day chay che do dev-lite, nhe hon ro ret:

```bash
docker compose up -d --build
```

Che do nay phu hop cho:

- dev va debug flow tong the
- ingest, OCR, parse, chunk, graph extract/upsert
- retrieval voi `hash` embedding de giam tai may

### 3. Chay full ML voi `bge-m3`

Khong can sua `.env` qua lai. Du an da co file override [docker-compose.full-ml.yml](D:\chatbot\docker-compose.full-ml.yml).

Chay full stack voi full ML:

```bash
docker compose -f docker-compose.yml -f docker-compose.full-ml.yml up -d --build
```

Neu stack da dang chay mode nhe va ban chi muon nang cap 2 service lien quan:

```bash
docker compose -f docker-compose.yml -f docker-compose.full-ml.yml up -d --build retrieval-service worker-runner
```

File override nay se tu dong:

- cai them `requirements/ml.txt` cho `retrieval-service`
- cai them `requirements/ml.txt` cho `worker-runner`
- bat `EMBEDDING_PROVIDER=bge-m3`
- bat `EMBEDDING_DEVICE=cuda`
- bat `EMBEDDING_USE_FP16=true`
- gan `gpus: all` cho `retrieval-service` va `worker-runner`
- bat `PRELOAD_EMBEDDING_MODEL=true`

### 3b. Chay semantic retrieval nhe hon voi `multilingual-e5-base`

Neu ban muon retrieval tot hon `hash` nhung nhe hon `bge-m3`, dung file override [docker-compose.e5.yml](D:\chatbot\docker-compose.e5.yml).

Chay full stack voi `e5-base`:

```bash
docker compose -f docker-compose.yml -f docker-compose.e5.yml up -d --build
```

Neu chi can nang cap 2 service lien quan den embedding:

```bash
docker compose -f docker-compose.yml -f docker-compose.e5.yml up -d --build retrieval-service worker-runner
```

File override nay se:

- cai them `requirements/ml.txt` cho `retrieval-service`
- cai them `requirements/ml.txt` cho `worker-runner`
- bat `EMBEDDING_PROVIDER=e5`
- bat `EMBEDDING_MODEL_NAME=intfloat/multilingual-e5-base`
- bat `EMBEDDING_DEVICE=cuda`
- bat `EMBEDDING_USE_FP16=true`
- gan `gpus: all` cho `retrieval-service` va `worker-runner`
- bat `PRELOAD_EMBEDDING_MODEL=true`

Service URLs:

- Web: `http://localhost:3000`
- API Gateway: `http://localhost:8000/docs`
- Document Service: `http://localhost:8001/docs`
- Retrieval Service: `http://localhost:8002/docs`
- Graph Service: `http://localhost:8003/docs`
- LLM Orchestrator: `http://localhost:8004/docs`
- Worker API: `http://localhost:8005/docs`
- RabbitMQ UI: `http://localhost:15672`
- Neo4j Browser: `http://localhost:7474`
- RustFS console: `http://localhost:9001`

### 4. Xem logs

```bash
docker compose logs -f api-gateway
docker compose logs -f document-service
docker compose logs -f worker-runner
```

### 5. Rebuild mot service

```bash
docker compose up -d --build retrieval-service
docker compose up -d --build worker worker-runner
```

Neu dang dung full ML override:

```bash
docker compose -f docker-compose.yml -f docker-compose.full-ml.yml up -d --build retrieval-service worker-runner
```

## Chay local theo tung service

Neu chay ngoai Docker, can doi cac host trong `.env` tu ten container sang `localhost`, vi du:

- `POSTGRES_DSN=postgresql+psycopg://postgres:postgres@localhost:5432/chatbot_graph`
- `REDIS_URL=redis://localhost:6379/0`
- `RABBITMQ_URL=amqp://guest:guest@localhost:5672//`
- `NEO4J_URI=bolt://localhost:7687`
- `RUSTFS_ENDPOINT=http://localhost:9000`

Nen export `PYTHONPATH` de cac service thay shared package:

```bash
$env:PYTHONPATH = "D:\\chatbot\\packages\\python\\enterprise_ai_core"
```

### Frontend

```bash
pnpm install
pnpm dev:web
```

### API Gateway

```bash
pip install -r requirements/base.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir services/api-gateway/app
```

### Document Service

```bash
pip install -r requirements/base.txt -r requirements/queue.txt -r requirements/storage.txt -r requirements/graph.txt
uvicorn main:app --host 0.0.0.0 --port 8001 --app-dir services/document-service/app
```

### Retrieval Service

```bash
pip install -r requirements/base.txt -r requirements/graph.txt
uvicorn main:app --host 0.0.0.0 --port 8002 --app-dir services/retrieval-service/app
```

Neu muon dung embedding model ML local nhu `bge-m3` hoac `multilingual-e5-base`, cai them:

```bash
pip install -r requirements/ml.txt
```

Neu may local da nhan GPU va `torch.cuda.is_available()` tra ve `True`, co the ep provider dung GPU:

```bash
$env:EMBEDDING_DEVICE = "cuda"
$env:EMBEDDING_USE_FP16 = "true"
```

Vi `multilingual-e5-*` la retrieval model bat doi xung, codebase da tu dong gan prefix:

- query se duoc embed theo dang `query: ...`
- chunk tai lieu se duoc embed theo dang `passage: ...`

### Graph Service

```bash
pip install -r requirements/base.txt -r requirements/graph.txt
uvicorn main:app --host 0.0.0.0 --port 8003 --app-dir services/graph-service/app
```

### LLM Orchestrator

```bash
pip install -r requirements/base.txt
uvicorn main:app --host 0.0.0.0 --port 8004 --app-dir services/llm-orchestrator/app
```

### Worker API

```bash
pip install -r requirements/base.txt
uvicorn main:app --host 0.0.0.0 --port 8005 --app-dir services/worker/app
```

### Celery worker runner

```bash
pip install -r requirements/base.txt -r requirements/queue.txt -r requirements/storage.txt -r requirements/graph.txt -r requirements/parsing.txt
cd services/worker/app
celery -A celery_app:celery_app worker --loglevel=info -Q document.parse,document.chunk,document.embed,graph.extract,graph.upsert,document.dead_letter
```

Neu muon worker-runner dung embedding model ML local, cai them:

```bash
pip install -r requirements/ml.txt
```

## Database migration va schema

Hien tai du an chua dung Alembic.

Schema PostgreSQL dang duoc khoi tao theo kieu code-first:

- moi service can DB se goi `init_db()`
- `init_db()` se thu `CREATE EXTENSION IF NOT EXISTS vector`
- sau do chay `Base.metadata.create_all(...)`

Dieu do co nghia la:

- voi moi truong moi, chi can bat service la bang se tu duoc tao
- voi thay doi schema nho, co the restart service de tao them bang/cot moi neu model thay doi tuong thich
- voi thay doi breaking schema, hien van can migration thu cong hoac reset volume database

Khuyen nghi dev:

- neu chi test flow moi tren moi truong local sach, xoa volume Postgres roi chay lai stack
- neu du lieu can giu lai, tu viet SQL migration tay truoc khi restart service

Neo4j schema/index duoc dam bao khi `graph-service` khoi dong. Buckets RustFS cung duoc `document-service` tao neu chua ton tai.

## Flow tong the cua he thong

### 1. Ingest tai lieu

`web` goi `api-gateway`, gateway forward multipart upload sang `document-service`.

`document-service` se:

- luu file raw vao RustFS bucket `documents-raw`
- tao `document`, `document_version`, `processing_job` trong PostgreSQL
- gan version hien hanh cho document
- publish job dau pipeline vao RabbitMQ

### 2. Pipeline xu ly nen

`worker-runner` chay chuoi Celery:

1. `document.parse`
2. `document.chunk`
3. `document.embed`
4. `graph.extract`
5. `graph.upsert`

Pipeline hien lam cac viec chinh:

- parse `txt`, `md`, `html`, `pdf`, `docx`, `pptx`, `xlsx`, image OCR
- sinh canonical document + parse report + provenance
- chunk theo heading/text span, giu metadata va source offsets
- reuse chunk theo content hash de ho tro incremental update co ban
- embed chunk va luu vector vao Postgres/PGVector
- Docker dev mac dinh dung `hash-1024`; full ML moi dung `bge-m3`
- extract entity/relation qua OpenRouter
- upsert document/entity/relation vao Neo4j theo version hien tai

Artifacts duoc luu o RustFS bucket `documents-artifacts`.

### 3. Query

`web` goi `api-gateway /api/v1/query`.

Gateway se:

- gui `QueryRequest` sang `retrieval-service`
- nhan contexts + retrieval plan
- gui question + contexts sang `llm-orchestrator`
- tra ve answer, answer type, policy summary, clarification question va citations

### 4. Retrieval

`retrieval-service` hien ho tro:

- intent classification nhu `lookup`, `compare`, `summary`, `temporal`
- query rewrite thanh sub-query
- hybrid retrieval tu vector chunks va graph evidence
- rerank va threshold de loc context yeu
- filter theo `document_ids`, `version_ids`, `effective_at`

### 5. Answer policy

`llm-orchestrator` chuan hoa cac outcome:

- `grounded`
- `partial`
- `no_answer`
- `refusal`
- `clarification`

Muc tieu la tranh hallucination khi context yeu hoac cau hoi vi pham policy.

## Flow tung service

### `apps/web`

- UI cho upload tai lieu
- goi gateway de xem documents, versions, jobs
- gui cau hoi va render answer kem citation

### `services/api-gateway`

- entrypoint duy nhat cho frontend
- proxy/compose request toi `document-service`, `retrieval-service`, `llm-orchestrator`, `worker`
- expose cac endpoint chinh:
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}/versions`
  - `POST /api/v1/documents/upload`
  - `POST /api/v1/documents/{document_id}/versions/upload`
  - `POST /api/v1/documents/{document_id}/reprocess`
  - `POST /api/v1/query`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/system/overview`

Luu y tenant:

- `GET /api/v1/documents` va `GET /api/v1/jobs` can query param `tenant_id`
- upload document/version can `tenant_id` trong form-data
- query da scope theo `tenant_id` trong JSON body

### `services/document-service`

- nhan upload moi hoac upload version moi
- chuan hoa metadata tai lieu
- luu raw file vao RustFS
- tao processing job
- ho tro reprocess theo document/version
- expose danh sach document va versions

### `services/worker`

- chi la control API cho processing jobs
- build nhe, chi can `requirements/base.txt`
- doc trang thai job tu PostgreSQL

### `services/worker/app/tasks.py`

- runtime thuc cua pipeline nen
- duoc `worker-runner` su dung voi full ML/OCR stack
- quan ly retry, dead-letter queue, artifact persistence
- cap nhat trang thai tung stage trong `processing_jobs`

### `services/retrieval-service`

- nhan `POST /api/v1/retrieve`
- lap retrieval plan
- combine vector search, graph candidates, rerank
- tra ve contexts da chuan hoa cho LLM layer

### `services/graph-service`

- expose graph inspection endpoints:
  - `GET /api/v1/entities/{entity_name}/neighbors`
  - `GET /api/v1/documents/{document_id}/entities`

### `services/llm-orchestrator`

- nhan `POST /api/v1/generate`
- ap prompt/policy chuan
- tra loi grounded neu context du tot
- tra `no_answer`, `clarification` hoac `refusal` khi can

## Mot so luu y van hanh

- `worker-runner` van la container nang nhat vi can parsing/OCR stack.
- `retrieval-service` o dev mode da duoc giam nhe bang `hash` embedding.
- `document-service` khong con keo parsing/OCR stack, nen build nhanh hon dang ke.
- `worker` chi la control API nen da duoc tach ra de build nhe hon.
- Chi khi bat full ML moi phai keo `torch`, `transformers`, `FlagEmbedding` va preload embedding model.
- Neu khong co `OPENROUTER_API_KEY`, flow extract/generate se khong hoan chinh.
- Hien chua co migration framework chinh thuc, nen moi thay doi schema production can duoc kiem soat thu cong.

## Health va kiem tra nhanh

- `GET /health` tren moi service
- `GET /health/ocr` tren `document-service`
  - trong image dev-lite, endpoint nay co the tra `degraded` vi OCR runtime khong duoc cai cung image
- `GET /health/embedding` tren `retrieval-service`
- `GET /api/v1/system/overview` tren gateway de xem tinh trang toan he thong
