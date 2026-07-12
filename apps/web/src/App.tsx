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
    <div className="grid min-h-screen text-ink-950 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="hidden border-r border-slate-200 bg-white/92 lg:block">
        <div className="sticky top-0 flex h-screen flex-col">
          <div className="border-b border-slate-200 px-5 py-5">
            <button
              className="flex w-full items-center gap-3 text-left"
              type="button"
              onClick={() => navigate({ name: "tenants" })}
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ink-950 text-white">
                <Database className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-bold leading-5">
                  Enterprise Graph RAG
                </div>
                <div className="truncate text-xs text-slate-500">{activeLabel}</div>
              </div>
            </button>
          </div>

          <div className="flex-1 space-y-6 overflow-y-auto px-4 py-5 app-scrollbar">
            <nav className="grid gap-2">
              <NavButton
                active={route.name === "dashboard"}
                onClick={() => navigate({ name: "dashboard" })}
              >
                <LayoutDashboard className="h-4 w-4" />
                Dashboard
              </NavButton>
              <NavButton
                active={route.name !== "dashboard"}
                onClick={() => navigate({ name: "tenants" })}
              >
                <Building2 className="h-4 w-4" />
                Tenants
              </NavButton>
            </nav>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                Current workspace
              </div>
              <div className="mt-2 text-sm font-semibold text-ink-950">{activeLabel}</div>
              <div className="mt-1 text-xs leading-5 text-slate-500">
                Dieu huong va control plane duoc gom vao sidebar ben trai de khung lam viec rong hon.
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <Server className="h-4 w-4 text-ocean-600" />
              API Gateway
              <span className="ml-auto h-1.5 w-1.5 rounded-full bg-leaf-500" />
            </div>
          </div>

          <div className="border-t border-slate-200 px-4 py-4">
            <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 shadow-panel">
              <Activity className="h-4 w-4 text-leaf-600" />
              Control plane
              <MessageSquareText className="ml-auto h-4 w-4 text-ocean-600" />
            </div>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur lg:hidden">
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <button
              className="flex items-center gap-3 text-left"
              type="button"
              onClick={() => navigate({ name: "tenants" })}
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ink-950 text-white">
                <Database className="h-5 w-5" />
              </div>
              <div>
                <div className="text-sm font-bold leading-5">
                  Enterprise Graph RAG
                </div>
                <div className="text-xs text-slate-500">{activeLabel}</div>
              </div>
            </button>
          </div>
        </header>

        <main
          className={cx(
            "mx-auto h-full w-full max-w-[1540px] px-5 py-5",
            route.name === "tenant" && "overflow-hidden lg:h-screen",
          )}
        >
          {route.name === "dashboard" ? (
            <Dashboard />
          ) : route.name === "tenant" ? (
            <TenantWorkspace
              tenantId={route.tenantId}
              onBack={() => navigate({ name: "tenants" })}
            />
          ) : (
            <TenantManager
              onOpenTenant={(tenantId) => navigate({ name: "tenant", tenantId })}
            />
          )}
        </main>
      </div>
    </div>
  );
}
