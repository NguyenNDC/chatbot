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
    <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-5">
      <section className="flex flex-col justify-between gap-4 border-b border-slate-200 pb-5 xl:flex-row xl:items-end">
        <div>
          <button className="btn-secondary mb-4" type="button" onClick={onBack}>
            <ChevronLeft className="h-4 w-4" />
            {tenantId}
          </button>
        </div>
      </section>

      <section className="grid min-h-0 gap-5 xl:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.1fr)]">
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
