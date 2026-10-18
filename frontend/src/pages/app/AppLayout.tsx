import { BarChart3, BellRing, LayoutDashboard, LogOut, Menu, Siren, X } from "lucide-react";
import { useState } from "react";
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { Logo } from "@/components/ui/Logo";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useAuth } from "@/lib/auth";
import { LiveProvider, useLive } from "@/lib/live";
import { formatInr, liveAlertFor } from "@/lib/store";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/app", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/app/incidents", label: "Incidents", icon: Siren, end: false },
  { to: "/app/alerts", label: "Alerts", icon: BellRing, end: false },
  { to: "/app/benchmark", label: "Benchmark", icon: BarChart3, end: false },
];

const TITLES: Record<string, string> = {
  "/app": "Overview",
  "/app/incidents": "Incidents",
  "/app/alerts": "Alerts",
  "/app/benchmark": "Benchmark & cost",
};

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user, logout } = useAuth();
  const { state } = useLive();
  const navigate = useNavigate();
  const counts: Record<string, number> = {
    "/app/incidents": [...state.incidents.values()].filter((i) => i.status === "open" && i.lane === "review").length,
    "/app/alerts": [...state.incidents.keys()].filter((id) => liveAlertFor(state.alerts, id)).length,
  };
  return (
    <div className="flex h-full flex-col gap-6 p-4">
      <Logo to="/app" className="px-2 pt-1" />
      <nav className="flex flex-col gap-1" aria-label="Sections">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                isActive ? "bg-accent-soft text-accent-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
              )
            }
          >
            <Icon className="size-[18px]" />
            <span className="flex-1">{label}</span>
            {counts[to] ? (
              <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold text-white">{counts[to]}</span>
            ) : null}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto rounded-2xl border border-line bg-bg p-3">
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-full bg-accent-soft font-semibold text-accent-ink">
            {user?.name.slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{user?.name}</p>
            <p className="truncate text-xs text-mute">{user?.email}</p>
          </div>
          <button
            type="button"
            onClick={async () => {
              await logout();
              navigate("/");
            }}
            className="grid size-8 place-items-center rounded-lg text-mute transition hover:bg-surface-2 hover:text-ink"
            aria-label="Log out"
            title="Log out"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { state, status } = useLive();
  const { pathname } = useLocation();
  const title = TITLES[pathname] ?? "Control room";
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur-xl sm:px-6">
      <button type="button" onClick={onMenu} className="grid size-9 place-items-center rounded-lg text-ink-2 hover:bg-surface-2 lg:hidden" aria-label="Open menu">
        <Menu className="size-5" />
      </button>
      <h1 className="font-display text-lg font-semibold">{title}</h1>
      <span
        className={cn(
          "ml-1 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
          status === "open" ? "bg-good/10 text-good" : "bg-warn/10 text-warn",
        )}
      >
        <span className={cn("size-1.5 rounded-full", status === "open" ? "bg-good" : "animate-pulse bg-warn")} />
        {status === "open" ? "Live" : "Reconnecting"}
      </span>
      <div className="ml-auto flex items-center gap-3">
        {state.cost && (
          <div className="hidden items-center gap-2 rounded-xl border border-line bg-surface px-3 py-1.5 text-xs md:flex" title="LLM cost at list price vs sending every report to a large reasoning model">
            <span className="font-mono font-semibold text-good">{formatInr(state.cost.sanket_inr)}</span>
            <span className="text-mute">vs</span>
            <span className="font-mono font-semibold text-danger">{formatInr(state.cost.counterfactual_inr)}</span>
          </div>
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}

function Shell() {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 border-r border-line bg-surface lg:block">
        <Sidebar />
      </aside>
      {menuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-black/40" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-72 border-r border-line bg-surface">
            <button type="button" onClick={() => setMenuOpen(false)} className="absolute right-3 top-4 grid size-8 place-items-center rounded-lg text-mute" aria-label="Close menu">
              <X className="size-4" />
            </button>
            <Sidebar onNavigate={() => setMenuOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setMenuOpen(true)} />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default function AppLayout() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="grid h-full place-items-center">
        <span className="size-8 animate-spin rounded-full border-2 border-line border-t-accent" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return (
    <LiveProvider>
      <Shell />
    </LiveProvider>
  );
}
