"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";

import { createTenant, deleteTenant, fetchTenants, type TenantRecord } from "../lib/api";

export function TenantManagementPage() {
  const [tenants, setTenants] = useState<TenantRecord[]>([]);
  const [tenantId, setTenantId] = useState("tenant-demo");
  const [displayName, setDisplayName] = useState("Tenant Demo");
  const [description, setDescription] = useState("Khong gian du lieu demo cho Graph RAG.");
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const reload = () => {
    startTransition(() => {
      void (async () => {
        const items = await fetchTenants();
        setTenants(items);
      })();
    });
  };

  useEffect(() => {
    reload();
  }, []);

  return (
    <section className="page-stack">
      <section className="panel panel-strong">
        <div className="panel-header">
          <div>
            <div className="eyebrow">Tenant Management</div>
            <h1 className="page-title">Quan ly tenant</h1>
            <p className="muted">
              Tao tenant moi, xoa tenant khong con dung, va di vao workspace document/chat cua tung tenant.
              Lenh xoa se don ca raw documents, OCR artifacts, vector/chunk, jobs, va graph data cua tenant.
            </p>
          </div>
          <div className="button-row compact-row">
            <div className="pill">{tenants.length} tenants</div>
            <button className="button ghost" type="button" onClick={reload}>
              Lam moi
            </button>
          </div>
        </div>

        <div className="input-grid three-columns">
          <input
            className="input"
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
            placeholder="tenant-demo"
          />
          <input
            className="input"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="Tenant Demo"
          />
          <input
            className="input"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Mo ta tenant"
          />
        </div>

        <div className="button-row">
          <button
            className="button"
            disabled={isPending}
            type="button"
            onClick={() => {
              startTransition(() => {
                void (async () => {
                  const tenant = await createTenant({ id: tenantId, displayName, description });
                  const items = await fetchTenants();
                  setTenants(items);
                  setMessage(`Da luu tenant ${tenant.display_name}.`);
                })();
              });
            }}
          >
            {isPending ? "Dang luu..." : "Tao tenant"}
          </button>
        </div>

        {message ? <p className="muted">{message}</p> : null}
      </section>

      <section className="tenant-card-grid">
        {tenants.map((tenant) => (
          <article className="tenant-card" key={tenant.id}>
            <div className="tenant-card-top">
              <div>
                <strong>{tenant.display_name}</strong>
                <div className="muted">{tenant.id}</div>
              </div>
              <div className="pill">{tenant.document_count} docs</div>
            </div>

            <p className="muted">{tenant.description || "Chua co mo ta."}</p>

            <div className="button-row">
              <Link className="button" href={`/tenants/${encodeURIComponent(tenant.id)}`}>
                Mo workspace
              </Link>
              <button
                className="button ghost"
                type="button"
                onClick={() => {
                  const confirmed = window.confirm(
                    `Xoa tenant ${tenant.id}? Hanh dong nay se xoa toan bo raw documents, artifacts, chunks, jobs, va graph data.`,
                  );
                  if (!confirmed) {
                    return;
                  }
                  startTransition(() => {
                    void (async () => {
                      await deleteTenant(tenant.id);
                      const items = await fetchTenants();
                      setTenants(items);
                      setMessage(`Da xoa tenant ${tenant.id}.`);
                    })();
                  });
                }}
              >
                Xoa
              </button>
            </div>
          </article>
        ))}
      </section>
    </section>
  );
}
