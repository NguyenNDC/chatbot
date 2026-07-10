import { DocumentPanel } from "./document-panel";
import { JobsPanel } from "./jobs-panel";
import { QueryPanel } from "./query-panel";
import { SystemStatus } from "./system-status";

export function DashboardShell() {
  return (
    <main className="page-shell">
      <section className="hero">
        <div className="hero-top">
          <div>
            <div className="eyebrow">Enterprise Graph RAG Console</div>
            <h1>Control plane for your knowledge system.</h1>
          </div>
          <div className="pill">OpenRouter + RustFS + FastAPI + Next.js</div>
        </div>
        <p>
          This starter console gives your team one place to inspect document ingest,
          grounded answers, and service health while the deeper Graph RAG adapters are being
          connected to PostgreSQL, PGVector, Neo4j, Redis and RabbitMQ.
        </p>
        <div className="metrics">
          <div className="metric">
            <div className="metric-label">UI Surface</div>
            <div className="metric-value">Dashboard</div>
          </div>
          <div className="metric">
            <div className="metric-label">Gateway Mode</div>
            <div className="metric-value">Orchestrated</div>
          </div>
          <div className="metric">
            <div className="metric-label">Storage Path</div>
            <div className="metric-value">RustFS</div>
          </div>
          <div className="metric">
            <div className="metric-label">LLM Path</div>
            <div className="metric-value">OpenRouter</div>
          </div>
        </div>
      </section>

      <section className="dashboard-grid">
        <div className="stack">
          <QueryPanel />
        </div>
        <div className="stack">
          <SystemStatus />
          <JobsPanel />
          <DocumentPanel />
        </div>
      </section>
    </main>
  );
}
