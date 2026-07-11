import Link from "next/link";

import { DocumentPanel } from "./document-panel";
import { QueryPanel } from "./query-panel";

export function TenantWorkspaceShell({ tenantId }: { tenantId: string }) {
  return (
    <main className="page-shell">
      <section className="panel panel-strong">
        <div className="panel-header">
          <div>
            <div className="eyebrow">Tenant Workspace</div>
            <h1 className="page-title">{tenantId}</h1>
            <p className="muted">
              Man hinh van hanh 2 nua: ben trai quan ly tai lieu va preview OCR, ben phai chat/query theo tenant.
            </p>
          </div>
          <Link className="button ghost" href="/tenants">
            Quay lai danh sach tenant
          </Link>
        </div>
      </section>

      <section className="workspace-grid">
        <DocumentPanel tenantId={tenantId} />
        <QueryPanel tenantId={tenantId} />
      </section>
    </main>
  );
}
