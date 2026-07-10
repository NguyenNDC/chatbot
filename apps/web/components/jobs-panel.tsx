"use client";

import { useEffect, useState, useTransition } from "react";

import { fetchJobs, type JobRecord } from "../lib/api";

export function JobsPanel() {
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    startTransition(() => {
      void (async () => {
        const items = await fetchJobs();
        setJobs(items);
      })();
    });
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h3>Pipeline Jobs</h3>
          <p className="muted">Track queue-backed stage transitions for uploaded documents.</p>
        </div>
        <div className="pill">{isPending ? "Refreshing" : `${jobs.length} jobs`}</div>
      </div>
      <div className="list-box">
        {jobs.length === 0 ? (
          <div className="muted">No jobs yet.</div>
        ) : (
          jobs.map((job) => (
            <div className="status-item" key={job.id}>
              <strong>{job.job_type}</strong>
              <div className={job.status === "completed" ? "status-ok" : "status-warn"}>
                {job.status}
              </div>
              <div className="muted">{job.document_id}</div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
