"use client";

import { useEffect, useState, useTransition } from "react";

import {
  fetchDocuments,
  type DocumentRecord,
  uploadDocument,
} from "../lib/api";

export function DocumentPanel() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [tenantId, setTenantId] = useState("tenant-demo");
  const [title, setTitle] = useState("SOP cap phat PPE");
  const [tags, setTags] = useState("ppe, sop");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    startTransition(() => {
      void (async () => {
        const items = await fetchDocuments();
        setDocuments(items);
      })();
    });
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h3>Document Intake</h3>
          <p className="muted">Seed test documents into the ingest queue from the dashboard.</p>
        </div>
        <div className="pill">{documents.length} docs</div>
      </div>

      <div className="input-grid">
        <input
          className="input"
          value={tenantId}
          onChange={(event) => setTenantId(event.target.value)}
          placeholder="Tenant ID"
        />
        <input
          className="input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Document title"
        />
        <input
          className="input"
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder="Tags, comma separated"
        />
        <input
          className="input"
          type="file"
          onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
        />
        <div className="button-row">
          <button
            className="button secondary"
            disabled={isPending}
            onClick={() => {
              startTransition(() => {
                void (async () => {
                  if (!selectedFile) {
                    setMessage("Please choose a file before uploading.");
                    return;
                  }
                  const response = await uploadDocument({
                    tenantId,
                    title,
                    tags,
                    file: selectedFile,
                  });
                  const items = await fetchDocuments();
                  setDocuments(items);
                  setMessage(
                    `Uploaded ${response.document.title}. Root job ${response.root_job.job_type} is ${response.root_job.status}.`,
                  );
                })();
              });
            }}
          >
            {isPending ? "Uploading..." : "Upload to RustFS"}
          </button>
        </div>
      </div>

      {message ? <p className="muted">{message}</p> : null}

      <div className="list-box">
        {documents.length === 0 ? (
          <div className="muted">No documents yet.</div>
        ) : (
          documents.map((document) => (
            <div className="doc-item" key={document.id}>
              <strong>{document.title}</strong>
              <div className="muted">
                {document.file_name} · {document.status} · {document.version}
              </div>
              <div className="muted">
                {document.current_job_type ?? "no-job"} · {document.current_job_status ?? "n/a"}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
