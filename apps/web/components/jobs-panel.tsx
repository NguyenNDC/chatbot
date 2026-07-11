"use client";

import { useEffect, useState, useTransition } from "react";

import { fetchJobs, type JobRecord } from "../lib/api";

const stageLabels: Record<string, string> = {
  "document.parse": "Parse canonical document",
  "document.chunk": "Chunk + provenance",
  "document.embed": "Embed vao PGVector",
  "graph.extract": "Entity extraction",
  "graph.upsert": "Neo4j upsert",
  "document.dead_letter": "Dead letter",
};

function statusClassName(status: string) {
  return status === "completed" ? "status-ok" : status === "running" ? "status-live" : "status-warn";
}

function hasActiveJobs(jobs: JobRecord[]) {
  return jobs.some((job) => job.status === "queued" || job.status === "running");
}

export function JobsPanel({ tenantId }: { tenantId: string }) {
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [isPending, startTransition] = useTransition();

  const reloadJobs = () => {
    startTransition(() => {
      void (async () => {
        const items = await fetchJobs(tenantId);
        setJobs(items);
      })();
    });
  };

  useEffect(() => {
    reloadJobs();
  }, [tenantId]);

  useEffect(() => {
    if (!tenantId || !hasActiveJobs(jobs)) {
      return;
    }

    const timer = window.setInterval(() => {
      reloadJobs();
    }, 5000);

    return () => window.clearInterval(timer);
  }, [jobs, tenantId]);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>Processing Jobs</h2>
          <p className="muted">
            Theo doi stage cua Celery pipeline de biet document dang dung o parse, embed hay graph.
          </p>
          <div className="tenant-inline">Tenant scope: {tenantId}</div>
        </div>
        <div className="button-row compact-row">
          <div className="pill">{isPending ? "Dang tai..." : `${jobs.length} jobs`}</div>
          <button className="button ghost" type="button" onClick={reloadJobs}>
            {isPending ? "Dang dong bo..." : "Lam moi"}
          </button>
        </div>
      </div>

      <div className="list-box">
        {jobs.length === 0 ? (
          <div className="muted">Chua co processing job nao.</div>
        ) : (
          jobs.map((job) => (
            <article className="job-card" key={job.id}>
              <div className="job-card-top">
                <div>
                  <strong>{stageLabels[job.job_type] ?? job.job_type}</strong>
                  <div className="muted">{job.job_type}</div>
                </div>
                <div className={statusClassName(job.status)}>{job.status}</div>
              </div>

              <div className="document-meta-grid">
                <div>
                  <span className="meta-label">queue</span>
                  <div>{job.queue_name}</div>
                </div>
                <div>
                  <span className="meta-label">attempts</span>
                  <div>{job.attempts}</div>
                </div>
                <div>
                  <span className="meta-label">document</span>
                  <div className="tiny">{job.document_id}</div>
                </div>
                <div>
                  <span className="meta-label">created</span>
                  <div>{new Date(job.created_at).toLocaleString()}</div>
                </div>
              </div>

              {job.error_message ? <div className="status-warn">{job.error_message}</div> : null}
            </article>
          ))
        )}
      </div>
    </section>
  );
}
