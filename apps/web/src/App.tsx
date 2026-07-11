import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Building2,
  Database,
  LayoutDashboard,
  MessageSquareText,
  Server,
} from "lucide-react";

import { Dashboard } from "./components/Dashboard";
import { TenantManager } from "./components/TenantManager";
import { TenantWorkspace } from "./components/TenantWorkspace";
import { cx } from "./lib/format";

type Route =
  | { name: "dashboard" }
  | { name: "tenants" }
  | { name: "tenant"; tenantId: string };

function parseRoute(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const [segment, value] = hash.split("/");
  if (segment === "dashboard") {
    return { name: "dashboard" };
  }
  if (segment === "tenant" && value) {
    return { name: "tenant", tenantId: decodeURIComponent(value) };
  }
  return { name: "tenants" };
}

function navigate(route: Route) {
  if (route.name === "dashboard") {
    window.location.hash = "/dashboard";
  } else if (route.name === "tenant") {
    window.location.hash = `/tenant/${encodeURIComponent(route.tenantId)}`;
  } else {
    window.location.hash = "/tenants";
  }
}

function NavButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      className={cx(
        "inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold transition",
        active
          ? "bg-ink-950 text-white shadow-sm"
          : "text-slate-600 hover:bg-slate-100 hover:text-ink-950",
      )}
      type="button"
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute());

  useEffect(() => {
    const onHashChange = () => setRoute(parseRoute());
    window.addEventListener("hashchange", onHashChange);
    if (!window.location.hash) {
      navigate({ name: "tenants" });
    }
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const activeLabel = useMemo(() => {
    if (route.name === "tenant") {
      return route.tenantId;
    }
    if (route.name === "dashboard") {
      return "Dashboard";
    }
    return "Quan ly tenant";
  }, [route]);

  return (
    <div className="min-h-screen text-ink-950">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1540px] items-center justify-between gap-4 px-5 py-3">
          <button
            className="flex items-center gap-3 text-left"
            type="button"
            onClick={() => navigate({ name: "tenants" })}
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ink-950 text-white">
              <Database className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-bold leading-5">Enterprise Graph RAG</div>
              <div className="text-xs text-slate-500">{activeLabel}</div>
            </div>
          </button>

          <nav className="hidden items-center gap-1 md:flex">
            <NavButton active={route.name === "dashboard"} onClick={() => navigate({ name: "dashboard" })}>
              <LayoutDashboard className="h-4 w-4" />
              Dashboard
            </NavButton>
            <NavButton active={route.name !== "dashboard"} onClick={() => navigate({ name: "tenants" })}>
              <Building2 className="h-4 w-4" />
              Tenants
            </NavButton>
          </nav>

          <div className="hidden items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 lg:flex">
            <Server className="h-4 w-4 text-ocean-600" />
            API Gateway
            <span className="h-1.5 w-1.5 rounded-full bg-leaf-500" />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1540px] px-5 py-5">
        {route.name === "dashboard" ? (
          <Dashboard />
        ) : route.name === "tenant" ? (
          <TenantWorkspace
            tenantId={route.tenantId}
            onBack={() => navigate({ name: "tenants" })}
          />
        ) : (
          <TenantManager onOpenTenant={(tenantId) => navigate({ name: "tenant", tenantId })} />
        )}
      </main>

      <div className="fixed bottom-4 right-4 hidden items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 shadow-panel xl:flex">
        <Activity className="h-4 w-4 text-leaf-600" />
        Control plane
        <MessageSquareText className="ml-2 h-4 w-4 text-ocean-600" />
        Chat ready
      </div>
    </div>
  );
}
