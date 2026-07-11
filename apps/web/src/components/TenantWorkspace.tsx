import { useState } from "react";
import { ChevronLeft, Files, MessageSquareText } from "lucide-react";

import type { DocumentRecord } from "../lib/api";
import { ChatPanel } from "./ChatPanel";
import { DocumentPanel } from "./DocumentPanel";

export function TenantWorkspace({
  tenantId,
  onBack,
}: {
  tenantId: string;
  onBack: () => void;
}) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);

  return (
    <div className="grid gap-5">
      <section className="flex flex-col justify-between gap-4 border-b border-slate-200 pb-5 xl:flex-row xl:items-end">
        <div>
          <button className="btn-secondary mb-4" type="button" onClick={onBack}>
            <ChevronLeft className="h-4 w-4" />
            Tenants
          </button>
          <div className="label">Tenant workspace</div>
          <h1 className="mt-1 text-2xl font-bold tracking-normal">
            {tenantId}
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            Upload tai lieu, theo doi RAG pipeline va chat truc tiep voi kho tri
            thuc cua tenant trong cung mot man hinh.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge-neutral">
            <Files className="h-3.5 w-3.5" />
            {documents.length} documents
          </span>
          <span className="badge-neutral">
            <MessageSquareText className="h-3.5 w-3.5" />
            Chat sessions
          </span>
        </div>
      </section>

      <section className="grid gap-5 grid-cols-2">
        <DocumentPanel
          tenantId={tenantId}
          documents={documents}
          onDocumentsChange={setDocuments}
        />
        <ChatPanel tenantId={tenantId} documents={documents} />
      </section>
    </div>
  );
}
