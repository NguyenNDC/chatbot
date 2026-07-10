"use client";

import { useEffect, useState } from "react";

import { fetchSystemOverview, type ServiceStatusMap } from "../lib/api";

const serviceLabels: Record<string, string> = {
  document_service: "Document service",
  retrieval_service: "Retrieval service",
  graph_service: "Graph service",
  llm_service: "LLM orchestrator",
  worker_service: "Worker control API",
  "api-gateway": "API gateway",
};

function statusClassName(status: string) {
  return status === "ok" ? "status-ok" : "status-warn";
}

export function SystemStatus() {
  const [services, setServices] = useState<ServiceStatusMap>({});

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const next = await fetchSystemOverview();
        if (mounted) {
          setServices(next);
        }
      } catch {
        if (mounted) {
          setServices({
            "api-gateway": { status: "unavailable", detail: "Khong lay duoc system overview" },
          });
        }
      }
    }
    void load();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>System Health</h2>
          <p className="muted">Tinh trang ket noi tu gateway den cac backend trong flow nghiep vu.</p>
        </div>
        <div className="pill">Gateway probe</div>
      </div>

      <div className="list-box">
        {Object.keys(services).length === 0 ? (
          <div className="muted">Dang tai service status...</div>
        ) : (
          Object.entries(services).map(([name, value]) => (
            <article className="service-card" key={name}>
              <div className="service-card-top">
                <strong>{serviceLabels[name] ?? name}</strong>
                <div className={statusClassName(value.status)}>{value.status}</div>
              </div>
              <div className="muted">{value.detail ?? "Healthy"}</div>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
