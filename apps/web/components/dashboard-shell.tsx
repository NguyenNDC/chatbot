import { DocumentPanel } from "./document-panel";
import { JobsPanel } from "./jobs-panel";
import { PipelineOverview } from "./pipeline-overview";
import { QueryPanel } from "./query-panel";
import { SystemStatus } from "./system-status";

export function DashboardShell() {
  return (
    <main className="page-shell">
      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow">Enterprise Chatbot Graph RAG</div>
          <h1>Bang dieu khien ingest, retrieval va answer policy trong cung mot man hinh.</h1>
          <p>
            Giao dien nay phuc vu dung flow cua du an: upload tai lieu vao RustFS, theo doi
            Celery pipeline parse/chunk/embed/graph, kiem tra tinh trang service, va chay query
            qua gateway de xem answer, citations va retrieval context.
          </p>
        </div>

        <div className="hero-cards">
          <div className="hero-card">
            <span>Ingest</span>
            <strong>Document + Version</strong>
            <p>Quan ly upload, version moi va reprocess pipeline.</p>
          </div>
          <div className="hero-card">
            <span>Storage</span>
            <strong>Postgres + PGVector + RustFS</strong>
            <p>Metadata, chunk embeddings va artifacts duoc tach ro tung lop.</p>
          </div>
          <div className="hero-card">
            <span>Graph</span>
            <strong>Neo4j + extraction</strong>
            <p>Entity va relation duoc upsert sau cac stage processing nen.</p>
          </div>
          <div className="hero-card">
            <span>Answering</span>
            <strong>Gateway + LLM policy</strong>
            <p>Co grounded, partial, no-answer, refusal va clarification.</p>
          </div>
        </div>
      </section>

      <PipelineOverview />

      <section className="dashboard-grid">
        <div className="stack">
          <DocumentPanel />
          <JobsPanel />
        </div>
        <div className="stack">
          <QueryPanel />
          <SystemStatus />
        </div>
      </section>
    </main>
  );
}
