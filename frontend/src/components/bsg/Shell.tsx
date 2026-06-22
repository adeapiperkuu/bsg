import { Link, useRouterState, useNavigate } from "@tanstack/react-router";
import {
  LayoutDashboard, Activity, ShieldCheck, Users, GitBranch, Briefcase,
  BookOpen, FolderKanban, ListChecks, Settings2, FileText, Folder, BarChart3, Settings,
  Bell, Sun, Moon, ChevronDown, Search, Building2, Crown, UserCog, Signal,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { useRole, type Role } from "@/lib/bsg/role";
import { cn } from "@/lib/utils";
import { notifications } from "@/lib/bsg/data";
import { StatusPill } from "./widgets";

type NavItem = { to: string; label: string; icon: React.ComponentType<{ className?: string }> };

const internalNav: { section: string; items: NavItem[] }[] = [
  { section: "Agents", items: [
    { to: "/dashboard", label: "Operational Tower", icon: LayoutDashboard },
    { to: "/delivery", label: "Delivery Performance", icon: Activity },
    { to: "/quality", label: "Quality Intelligence", icon: ShieldCheck },
    { to: "/workforce", label: "Workforce & Capability", icon: Users },
    { to: "/governance", label: "Project Governance", icon: GitBranch },
    { to: "/client-intelligence", label: "Client Intelligence", icon: Briefcase },
  ]},
  { section: "Workspace", items: [
    { to: "/knowledge", label: "Knowledge Agent", icon: BookOpen },
    { to: "/projects", label: "Projects", icon: FolderKanban },
    { to: "/pm-console", label: "PM Console", icon: ListChecks },
    { to: "/admin", label: "Admin Console", icon: Settings2 },
  ]},
  { section: "Reporting", items: [
    { to: "/reports", label: "Reports", icon: FileText },
    { to: "/documents", label: "Documents", icon: Folder },
    { to: "/analytics", label: "Analytics", icon: BarChart3 },
  ]},
  { section: "System", items: [
    { to: "/settings", label: "Settings", icon: Settings },
  ]},
];

const clientNav: { section: string; items: NavItem[] }[] = [
  { section: "Client Portal", items: [
    { to: "/client", label: "My Projects", icon: LayoutDashboard },
    { to: "/client/status", label: "Delivery Status", icon: Activity },
    { to: "/client/reports", label: "Reports", icon: FileText },
    { to: "/client/ask", label: "Ask Agent", icon: BookOpen },
  ]},
];

export function Shell({ children }: { children: ReactNode }) {
  const { role, setRole, theme, toggleTheme } = useRole();
  const [collapsed, setCollapsed] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [roleOpen, setRoleOpen] = useState(false);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  const isClient = role === "Client";
  const isLeadership = role === "BSG Leadership";
  const nav = isClient ? clientNav : internalNav;

  const onRoleChange = (r: Role) => {
    setRole(r);
    setRoleOpen(false);
    if (r === "Client") navigate({ to: "/client" });
    else if (r === "BSG Leadership") navigate({ to: "/leadership" });
    else navigate({ to: "/dashboard" });
  };

  const currentTitle =
    [...internalNav, ...clientNav].flatMap((s) => s.items).find((i) => i.to === pathname)?.label ??
    (pathname === "/leadership" ? "Leadership Cockpit" : pathname === "/client" ? "My Projects" : "BSG Insights Hub");

  return (
    <div className="flex min-h-screen w-full bg-background text-foreground">
      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-4">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
            <Signal className="h-4 w-4" />
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="text-sm font-semibold tracking-tight">BSG</div>
              <div className="-mt-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">Insights Hub</div>
            </div>
          )}
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {nav.map((sec) => (
            <div key={sec.section} className="mb-4">
              {!collapsed && (
                <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{sec.section}</div>
              )}
              <ul className="space-y-0.5">
                {sec.items.map((item) => {
                  const active = pathname === item.to;
                  const Icon = item.icon;
                  return (
                    <li key={item.to}>
                      <Link
                        to={item.to}
                        title={collapsed ? item.label : undefined}
                        className={cn(
                          "group relative flex items-center gap-2.5 rounded-md px-2 py-2 text-sm transition-colors",
                          active
                            ? "bg-sidebar-accent text-sidebar-accent-foreground"
                            : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                        )}
                      >
                        {active && (
                          <span className="absolute inset-y-1 left-0 w-0.5 rounded-r bg-[color:var(--brand)]" />
                        )}
                        <Icon className="h-4 w-4 shrink-0" />
                        {!collapsed && <span className="truncate">{item.label}</span>}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="border-t border-sidebar-border px-4 py-2.5 text-left text-xs text-muted-foreground hover:text-foreground"
        >
          {collapsed ? "›" : "‹  Collapse"}
        </button>
      </aside>

      {/* Main area */}
      <div className={cn("flex min-h-screen w-full flex-col transition-[padding] duration-200", collapsed ? "pl-16" : "pl-60")}>
        {/* Header */}
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-background/95 px-6 backdrop-blur">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-foreground">{currentTitle}</div>
            <div className="text-[11px] text-muted-foreground">
              Insights Hub <span className="px-1">/</span> {currentTitle}
            </div>
          </div>

          <div className="hidden items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-muted-foreground md:flex">
            <Search className="h-3.5 w-3.5" /> Search projects, alerts, docs…
          </div>

          {/* Role switcher */}
          <div className="relative">
            <button
              onClick={() => setRoleOpen((o) => !o)}
              className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium hover:bg-elevated"
            >
              {role === "Delivery Manager" ? <UserCog className="h-3.5 w-3.5" /> : role === "Client" ? <Building2 className="h-3.5 w-3.5" /> : <Crown className="h-3.5 w-3.5" />}
              {role}
              <ChevronDown className="h-3 w-3 opacity-60" />
            </button>
            {roleOpen && (
              <div className="absolute right-0 top-full z-30 mt-1 w-56 rounded-md border border-border bg-popover p-1 text-sm">
                {(["Delivery Manager", "Client", "BSG Leadership"] as Role[]).map((r) => (
                  <button
                    key={r}
                    onClick={() => onRoleChange(r)}
                    className={cn("flex w-full items-center justify-between rounded px-2.5 py-1.5 text-left text-xs hover:bg-elevated", r === role && "text-[color:var(--brand)]")}
                  >
                    {r}
                    {r === role && <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--brand)]" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button onClick={toggleTheme} className="grid h-8 w-8 place-items-center rounded-md border border-border bg-card hover:bg-elevated">
            {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
          </button>

          {/* Notifications */}
          <div className="relative">
            <button onClick={() => setNotifOpen((o) => !o)} className="relative grid h-8 w-8 place-items-center rounded-md border border-border bg-card hover:bg-elevated">
              <Bell className="h-3.5 w-3.5" />
              <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-[color:var(--danger)]" />
            </button>
            {notifOpen && (
              <div className="absolute right-0 top-full z-30 mt-1 w-80 rounded-md border border-border bg-popover p-2 text-sm">
                <div className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Recent alerts</div>
                <ul className="space-y-1">
                  {notifications.map((n) => (
                    <li key={n.title} className="rounded p-2 hover:bg-elevated">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-medium">{n.title}</span>
                        <StatusPill status={n.sev} />
                      </div>
                      <div className="mt-0.5 text-[10px] text-muted-foreground">{n.time}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Avatar */}
          <div className="flex items-center gap-2 rounded-md border border-border bg-card px-2 py-1">
            <div className="grid h-6 w-6 place-items-center rounded-full bg-[color:var(--brand)]/20 text-[10px] font-semibold text-[color:var(--brand)]">MC</div>
            <div className="text-xs">
              <div className="font-medium leading-none">Maya Chen</div>
              <div className="text-[10px] text-muted-foreground">{isClient ? "Client · Aurora" : isLeadership ? "Leadership" : "Delivery PM"}</div>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1440px] flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
