"use client";

import { useEffect, useState } from "react";

import { fetchSystemOverview, type ServiceStatusMap } from "../lib/api";

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
            "api-gateway": { status: "unavailable", detail: "Gateway overview unavailable" },
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
          <h3>Service Health</h3>
          <p className="muted">Runtime reachability from the gateway to downstream services.</p>
        </div>
        <div className="pill">Live view</div>
      </div>
      <div className="list-box">
        {Object.keys(services).length === 0 ? (
          <div className="muted">Loading service status...</div>
        ) : (
          Object.entries(services).map(([name, value]) => (
            <div className="status-item" key={name}>
              <strong>{name}</strong>
              <div className={value.status === "ok" ? "status-ok" : "status-warn"}>
                {value.status}
              </div>
              {value.detail ? <div className="muted">{value.detail}</div> : null}
            </div>
          ))
        )}
      </div>
    </section>
  );
}

