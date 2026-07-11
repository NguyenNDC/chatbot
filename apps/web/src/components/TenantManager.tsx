import { FormEvent, useEffect, useMemo, useState } from "react";
import { ArrowRight, Building2, Plus, RefreshCw, Search, Trash2 } from "lucide-react";

import { createTenant, deleteTenant, fetchTenants, type TenantRecord } from "../lib/api";
import { cx, formatDateTime } from "../lib/format";

export function TenantManager({ onOpenTenant }: { onOpenTenant: (tenantId: string) => void }) {
  const [tenants, setTenants] = useState<TenantRecord[]>([]);
  const [query, setQuery] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setMessage(null);
    try {
      setTenants(await fetchTenants());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot load tenants");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filteredTenants = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) {
      return tenants;
    }
    return tenants.filter((tenant) =>
      [tenant.id, tenant.display_name, tenant.description ?? ""].join(" ").toLowerCase().includes(keyword),
    );
  }, [query, tenants]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!tenantId.trim() || !displayName.trim()) {
      setMessage("Can nhap tenant id va ten hien thi.");
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      await createTenant({
        id: tenantId.trim(),
        displayName: displayName.trim(),
        description: description.trim(),
      });
      setTenantId("");
      setDisplayName("");
      setDescription("");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot create tenant");
    } finally {
      setLoading(false);
    }
  };

  const removeTenant = async (tenant: TenantRecord) => {
    if (!window.confirm(`Xoa tenant "${tenant.display_name}" va toan bo du lieu lien quan?`)) {
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      await deleteTenant(tenant.id);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot delete tenant");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid gap-5">
      <section className="flex flex-col justify-between gap-4 border-b border-slate-200 pb-5 lg:flex-row lg:items-end">
        <div>
          <div className="label">Tenant control plane</div>
          <h1 className="mt-1 text-2xl font-bold tracking-normal">Quan ly tenant</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            Moi tenant co kho tai lieu, graph, lich su chat va pipeline rieng. Xoa tenant se cleanup ca Postgres, RustFS va Neo4j.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="badge-neutral">{tenants.length} tenants</div>
          <button className="btn-secondary" type="button" onClick={load}>
            <RefreshCw className={cx("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </section>

      {message ? <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{message}</div> : null}

      <section className="grid gap-4 xl:grid-cols-[390px_minmax(0,1fr)]">
        <form className="surface grid gap-4 rounded-lg p-4" onSubmit={submit}>
          <div>
            <h2 className="text-sm font-bold">Tao tenant moi</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">Tenant id nen ngan gon, khong dau va on dinh vi duoc dung lam scope du lieu.</p>
          </div>
          <label className="grid gap-1.5">
            <span className="label">Tenant id</span>
            <input className="field" value={tenantId} onChange={(event) => setTenantId(event.target.value)} placeholder="phap-luat" />
          </label>
          <label className="grid gap-1.5">
            <span className="label">Ten hien thi</span>
            <input className="field" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Phong Phap Che" />
          </label>
          <label className="grid gap-1.5">
            <span className="label">Mo ta</span>
            <textarea className="textarea-field" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Kho tri thuc phuc vu hoi dap noi bo" />
          </label>
          <button className="btn-primary" disabled={loading} type="submit">
            <Plus className="h-4 w-4" />
            Tao tenant
          </button>
        </form>

        <div className="grid gap-3">
          <div className="surface flex items-center gap-3 rounded-lg p-3">
            <Search className="h-4 w-4 text-slate-400" />
            <input
              className="h-9 flex-1 bg-transparent text-sm outline-none"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Tim tenant theo id, ten hoac mo ta..."
            />
          </div>

          <div className="surface overflow-hidden rounded-lg">
            <div className="grid grid-cols-[minmax(0,1.4fr)_110px_150px_96px] gap-3 border-b border-slate-200 px-4 py-3 text-xs font-semibold uppercase tracking-normal text-slate-500">
              <span>Tenant</span>
              <span>Documents</span>
              <span>Created</span>
              <span />
            </div>
            <div className="divide-y divide-slate-100">
              {filteredTenants.length === 0 ? (
                <div className="p-6 text-sm text-slate-500">Chua co tenant phu hop.</div>
              ) : (
                filteredTenants.map((tenant) => (
                  <div
                    className="grid grid-cols-[minmax(0,1.4fr)_110px_150px_96px] items-center gap-3 px-4 py-3 transition hover:bg-slate-50"
                    key={tenant.id}
                  >
                    <button className="flex min-w-0 items-center gap-3 text-left" type="button" onClick={() => onOpenTenant(tenant.id)}>
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-slate-100 text-ocean-700">
                        <Building2 className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-bold text-ink-950">{tenant.display_name}</div>
                        <div className="truncate font-mono text-xs text-slate-500">{tenant.id}</div>
                      </div>
                    </button>
                    <div className="text-sm text-slate-700">{tenant.document_count}</div>
                    <div className="text-sm text-slate-500">{formatDateTime(tenant.created_at)}</div>
                    <div className="flex justify-end gap-1">
                      <button className="icon-btn" title="Mo workspace" type="button" onClick={() => onOpenTenant(tenant.id)}>
                        <ArrowRight className="h-4 w-4" />
                      </button>
                      <button className="icon-btn text-red-600 hover:bg-red-50" title="Xoa tenant" type="button" onClick={() => removeTenant(tenant)}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
