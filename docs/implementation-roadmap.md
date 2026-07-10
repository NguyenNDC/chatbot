# Enterprise Graph RAG Implementation Roadmap

Tài liệu này chốt lại kế hoạch triển khai các phần còn thiếu của hệ thống Graph RAG hiện tại, theo đúng thứ tự phụ thuộc để tránh viết lại kiến trúc.

## Hiện trạng

Repo hiện đã có:

* UI Next.js
* API Gateway
* Document Service
* Retrieval Service
* Graph Service
* LLM Orchestrator
* Worker service skeleton
* Docker Compose cho Postgres, Neo4j, Redis, RabbitMQ, RustFS

Repo hiện chưa có pipeline Graph RAG hoàn chỉnh chạy thật end-to-end.

## Mục tiêu

Hoàn thiện flow:

Upload
→ OCR
→ Chunk
→ Embedding
→ PGVector
→ Entity Extraction
→ Relation Extraction
→ Neo4j
→ Hybrid Retrieval
→ Context Builder
→ LLM

## 8 hạng mục triển khai còn thiếu

### 1. Upload file thật lên RustFS

Mục tiêu:

* Thay `POST /documents` từ tạo metadata in-memory sang upload file thật
* Tạo checksum
* Lưu metadata vào PostgreSQL
* Gắn `tenant_id`, `document_version`, `artifact_type`

Việc cần làm:

* Thêm multipart upload API ở `document-service`
* Tạo RustFS client theo chuẩn S3-compatible
* Lưu `document`, `document_version`, `artifact` vào PostgreSQL
* Sinh `job_id` để đẩy sang pipeline xử lý nền

Definition of done:

* Upload được file thật
* File nằm trong RustFS
* Metadata nằm trong PostgreSQL
* Gateway và UI thấy document mới

---

### 2. Worker + RabbitMQ

Mục tiêu:

* Biến các bước ingest thành async pipeline thật

Việc cần làm:

* Dùng `Celery` cho giai đoạn đầu
* Tạo queue:
  * `document.parse`
  * `document.chunk`
  * `document.embed`
  * `graph.extract`
  * `graph.upsert`
* Thêm bảng hoặc model `processing_job`
* Có retry, dead-letter queue và status API

Definition of done:

* Upload document tạo job
* Worker consume được job
* UI xem được trạng thái pipeline

---

### 3. Parsing, OCR, canonicalization và chunking

Mục tiêu:

* Có text sạch
* Có provenance rõ
* Có chunk ổn định cho embedding và extraction

Việc cần làm:

* Parser cho PDF, Word, Markdown, HTML trước
* OCR fallback cho scanned PDF và image
* Xây canonical JSON document model
* Thêm structural chunking + recursive chunking
* Lưu `parsed.json` và `chunks.json` vào RustFS

Definition of done:

* Mỗi document sinh ra `parsed.json`
* Mỗi document sinh ra `chunks.json`
* Chunk có `document_id`, `version`, `section`, `page`, `offset`

---

### 4. Embedding + PGVector

Mục tiêu:

* Chunk được embed và search thật bằng vector search

Việc cần làm:

* Tạo embedding service wrapper cho BGE-M3
* Thiết kế schema PostgreSQL/PGVector cho `chunk`, `chunk_embedding`
* Chạy batch embedding jobs
* Tạo HNSW index
* Cập nhật retrieval API để đọc từ PGVector thật

Definition of done:

* Query từ câu hỏi trả ra top-k chunk từ PGVector
* Có metadata filter theo tenant và permission

---

### 5. Entity extraction + relation extraction qua OpenRouter

Mục tiêu:

* Từ chunk sinh entity và relation theo schema chuẩn

Việc cần làm:

* Tạo prompt + JSON schema cho entity extraction
* Tạo prompt + JSON schema cho relation extraction
* Validation + retry
* Normalize entity name
* Lưu extraction result vào PostgreSQL trước khi upsert graph

Definition of done:

* Chunk sinh ra entity/relation JSON hợp lệ
* Có confidence score
* Có provenance

---

### 6. Build/update Neo4j

Mục tiêu:

* Có graph thật thay cho hard-code

Việc cần làm:

* Thiết kế node/edge schema
* Upsert Cypher theo `canonical_entity_id`
* Gắn provenance, effective date, source chunk
* Hỗ trợ incremental update khi document reprocess

Definition of done:

* `graph-service` query thật từ Neo4j
* Document mới hoặc version mới cập nhật graph được

---

### 7. Hybrid retrieval thật

Mục tiêu:

* Retrieval service dùng cả PGVector và Neo4j

Việc cần làm:

* Query classification mức nhẹ
* Vector search từ PGVector
* Entity expansion + Cypher search từ Neo4j
* Graph traversal 1–3 hops
* Merge score + optional reranker

Definition of done:

* Retrieval trả về context từ cả vector và graph
* Có `vector_score`, `graph_score`, `final_score`

---

### 8. Context builder + answer generation thật

Mục tiêu:

* `llm-orchestrator` gọi OpenRouter thật với grounded context

Việc cần làm:

* Context builder: dedupe, token budget, section stitching, citation map
* Dùng bộ prompt `core`, `policy`, `STT`
* Tạo OpenRouter adapter, fallback model, timeout, retry
* Trả structured answer + citation contract

Definition of done:

* `/query` trả lời bằng OpenRouter thật
* Có citation trace tới `document`, `version`, `page`, `chunk`
* Có no-answer và refusal path

## Thứ tự triển khai theo phase

### Phase 1

* Upload file thật lên RustFS
* Worker + RabbitMQ

### Phase 2

* Parsing, OCR, canonicalization và chunking
* Embedding + PGVector

Trạng thái hiện tại:

* Đã có parser baseline cho `txt`, `md`, `html`, `pdf`, `docx`
* Đã tích hợp Tesseract OCR cho image và scanned PDF
* Đã có canonical JSON artifact và `chunks.json`
* Đã có bảng `document_chunks` và `chunk_embeddings`
* Retrieval đã đọc chunk/vector thật từ PostgreSQL
* Đã bật BGE-M3 thật theo runtime hiện tại, nhưng cần môi trường đủ tài nguyên để load model ổn định

### Phase 3

* Entity extraction + relation extraction qua OpenRouter
* Build/update Neo4j

Trạng thái hiện tại:

* Đã có extraction structured output qua OpenRouter `openai/gpt-oss-20b`
* Đã lưu extraction result theo chunk vào PostgreSQL và RustFS
* Đã có Neo4j upsert cho `Document`, `Entity`, `MENTIONED_IN`, `RELATED_TO`
* `graph-service` đã query neighbor và entity theo document từ Neo4j thật
* Hybrid graph-aware retrieval đầy đủ vẫn để cho Phase 4

### Phase 4

* Hybrid retrieval thật
* Context builder + answer generation thật

## Ưu tiên kỹ thuật

* Làm schema PostgreSQL sớm trước khi worker pipeline đi sâu
* Chuẩn hóa artifact contract sớm:
  * raw file
  * parsed JSON
  * chunks JSON
  * extraction JSON
* Chưa cần auth/RBAC full ngay, nhưng mọi bảng và artifact phải có:
  * `tenant_id`
  * `document_id`
  * `version`
  * `permission tags`

## Definition of done toàn hệ

Khi hoàn tất toàn bộ roadmap, hệ thống phải chạy được flow sau:

1. Upload 1 file PDF hoặc Word
2. Worker parse + OCR nếu cần
3. Chunk + embed vào PGVector
4. Extract entity/relation qua OpenRouter
5. Upsert Neo4j
6. Query hybrid retrieval
7. Build context
8. LLM trả lời có citation đúng nguồn

## Ghi chú triển khai

Đây là roadmap implementation, không phải TDD tổng thể. Tài liệu này dùng để bám tiến độ code theo từng phase trên repo hiện tại.
