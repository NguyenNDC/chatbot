import { TenantWorkspaceShell } from "../../../components/tenant-workspace-shell";

export default async function TenantWorkspacePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  return <TenantWorkspaceShell tenantId={decodeURIComponent(tenantId)} />;
}
