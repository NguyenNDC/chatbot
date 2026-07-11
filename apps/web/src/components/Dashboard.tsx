import { useEffect, useState } from "react";
import { RefreshCw, Server, ShieldCheck } from "lucide-react";

import { fetchSystemOverview, type ServiceStatusMap } from "../lib/api";
import { cx, statusTone } from "../lib/format";

function StatusBadge({ status }: { status?: string }) {
  const tone = statusTone(status);
  return (
    <span
      className={cx(
        tone === "success" && "badge-success",
        tone === "live" && "badge-live",
        tone === "danger" && "badge-danger",
      )}
    >
      {status ?? "unknown"}
    </span>
  );
}

export function Dashboard() {
  const [services, setServices] = useState<ServiceStatusMap>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setServices(await fetchSystemOverview());
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Cannot load system overview");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const entries = Object.entries(services);
  const okCount = entries.filter(([, value]) => value.status === "ok").length;

  return (
    <div className="grid gap-5">
      <section className="grid gap-4 border-b border-slate-200 pb-5">
        <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
          <div>
            <div className="label">Operations</div>
            <h1 className="mt-1 text-2xl font-bold tracking-normal">Dashboard</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
              Trang tong quan nhe cho control plane. Tenant, ingest pipeline va chatbot van nam trong cac workspace rieng.
            </p>
          </div>
          <button className="btn-secondary" type="button" onClick={load}>
            <RefreshCw className={cx("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <div className="surface rounded-lg p-4">
          <div className="flex items-center justify-between">
            <span className="label">Service health</span>
            <ShieldCheck className="h-5 w-5 text-leaf-600" />
          </div>
          <div className="mt-3 text-3xl font-bold">{okCount}/{entries.length || 0}</div>
          <div className="mt-1 text-sm text-slate-500">services healthy</div>
        </div>
        <div className="surface rounded-lg p-4">
          <div className="flex items-center justify-between">
            <span className="label">Runtime</span>
            <Server className="h-5 w-5 text-ocean-600" />
          </div>
          <div className="mt-3 text-3xl font-bold">Docker</div>
          <div className="mt-1 text-sm text-slate-500">compose local stack</div>
        </div>
        <div className="surface rounded-lg p-4">
          <span className="label">Chat policy</span>
          <div className="mt-3 text-3xl font-bold">Grounded</div>
          <div className="mt-1 text-sm text-slate-500">citation-first answer contract</div>
        </div>
      </section>

      {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}

      <section className="surface overflow-hidden rounded-lg">
        <div className="border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-bold">Service map</h2>
        </div>
        <div className="divide-y divide-slate-100">
          {entries.length === 0 ? (
            <div className="p-5 text-sm text-slate-500">Chua co du lieu healthcheck.</div>
          ) : (
            entries.map(([name, value]) => (
              <div className="grid gap-3 px-4 py-3 md:grid-cols-[220px_120px_minmax(0,1fr)] md:items-center" key={name}>
                <div className="font-mono text-sm text-ink-800">{name}</div>
                <StatusBadge status={value.status} />
                <div className="truncate text-sm text-slate-500">{value.detail ?? "ready"}</div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
