const stages = [
  {
    key: "01",
    title: "Upload",
    detail: "Gateway -> document-service -> RustFS + Postgres metadata",
  },
  {
    key: "02",
    title: "Parse",
    detail: "Canonical document, OCR fallback, parse report, provenance",
  },
  {
    key: "03",
    title: "Chunk + Embed",
    detail: "Chunk heading-aware, incremental hash reuse, BGE-M3 vector",
  },
  {
    key: "04",
    title: "Graph",
    detail: "Entity extraction va Neo4j upsert theo document version",
  },
  {
    key: "05",
    title: "Query",
    detail: "Hybrid retrieval + answer policy + citations",
  },
];

export function PipelineOverview() {
  return (
    <section className="panel panel-strong">
      <div className="panel-header">
        <div>
          <h2>Flow Van Hanh</h2>
          <p className="muted">
            Day la flow thuc te ma UI can phan anh, khong phai mot dashboard marketing chung chung.
          </p>
        </div>
        <div className="pill">5 stages</div>
      </div>

      <div className="pipeline-grid">
        {stages.map((stage) => (
          <article className="pipeline-card" key={stage.key}>
            <div className="pipeline-index">{stage.key}</div>
            <strong>{stage.title}</strong>
            <p>{stage.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
