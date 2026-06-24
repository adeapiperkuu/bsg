import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard, Activity, ShieldCheck, Users, GitBranch, Briefcase,
  BookOpen, FolderKanban, ListChecks, Settings2, FileText, Folder, BarChart3, Settings,
  Bell, Sun, Moon, Search, Crown, Signal, LogOut, ChevronDown, Menu,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { useRole } from "@/lib/bsg/role";
import { roleLabel } from "@/lib/roleLabels";
import { cn } from "@/lib/utils";
import { notifications } from "@/lib/bsg/data";
import { StatusPill } from "./widgets";
import { useAuthStore } from "@/stores/useAuthStore";
import type { AppRole, MeUser } from "@/types/auth";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

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

const leadershipNav: { section: string; items: NavItem[] }[] = [
  { section: "Portfolio", items: [
    { to: "/leadership", label: "Leadership Cockpit", icon: Crown },
  ]},
];

const adminNav: { section: string; items: NavItem[] }[] = [
  { section: "Platform", items: [
    { to: "/admin", label: "Admin Console", icon: Settings2 },
    { to: "/admin/users", label: "Users", icon: Users },
  ]},
];

function navForUser(user: MeUser | null) {
  if (!user) return internalNav;
  switch (user.role as AppRole) {
    case "client":
      return clientNav;
    case "bsg_leadership":
      return leadershipNav;
    case "super_admin":
      return adminNav;
    default:
      return internalNav;
  }
}

function initials(name: string | null, email: string): string {
  if (name) {
    const parts = name.trim().split(/\s+/);
    return parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("") || email[0]?.toUpperCase() || "?";
  }
  return email[0]?.toUpperCase() ?? "?";
}

export function Shell({ children }: { children: ReactNode }) {
  const { theme, toggleTheme } = useRole();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  const nav = navForUser(user);

  const currentTitle =
    [...internalNav, ...clientNav, ...leadershipNav, ...adminNav].flatMap((s) => s.items).find((i) => i.to === pathname)?.label ??
    (pathname === "/leadership" ? "Leadership Cockpit" : pathname === "/client" ? "My Projects" : "BSG Insights Hub");

  async function handleLogout() {
    await logout();
    await navigate({ to: "/login" });
  }

  const navContent = (mobile = false) => (
    <>
      <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-4">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
          <Signal className="h-4 w-4" />
        </div>
        {(!collapsed || mobile) && (
          <div className="min-w-0">
            <div className="text-sm font-semibold tracking-tight">BSG</div>
            <div className="-mt-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">Insights Hub</div>
          </div>
        )}
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {nav.map((sec) => (
          <div key={sec.section} className="mb-4">
            {(!collapsed || mobile) && (
              <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{sec.section}</div>
            )}
            <ul className="space-y-0.5">
              {sec.items.map((item) => {
                const active =
                  item.to === "/admin"
                    ? pathname === "/admin" || pathname === "/admin/"
                    : pathname === item.to;
                const Icon = item.icon;
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      title={!mobile && collapsed ? item.label : undefined}
                      onClick={() => {
                        if (mobile) setMobileNavOpen(false);
                      }}
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
                      {(!collapsed || mobile) && <span className="truncate">{item.label}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </>
  );

  return (
    <div className="flex min-h-screen w-full bg-background text-foreground">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 hidden flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 md:flex",
          collapsed ? "w-16" : "w-60",
        )}
      >
        {navContent()}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="border-t border-sidebar-border px-4 py-2.5 text-left text-xs text-muted-foreground hover:text-foreground"
        >
          {collapsed ? "›" : "‹  Collapse"}
        </button>
      </aside>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="flex w-[min(20rem,85vw)] flex-col bg-sidebar p-0 text-sidebar-foreground">
          <SheetTitle className="sr-only">Navigation menu</SheetTitle>
          {navContent(true)}
        </SheetContent>
      </Sheet>

      <div className={cn("flex min-h-screen w-full flex-col transition-[padding] duration-200", collapsed ? "md:pl-16" : "md:pl-60")}>
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-border bg-background/95 px-3 backdrop-blur sm:gap-3 sm:px-4 md:px-6">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="grid h-9 w-9 place-items-center rounded-md border border-border bg-card hover:bg-elevated md:hidden"
            aria-label="Open navigation menu"
          >
            <Menu className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-foreground">{currentTitle}</div>
            <div className="hidden text-[11px] text-muted-foreground sm:block">
              Insights Hub <span className="px-1">/</span> {currentTitle}
            </div>
          </div>

          <div className="hidden items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-muted-foreground md:flex">
            <Search className="h-3.5 w-3.5" /> Search projects, alerts, docs…
          </div>

          <button onClick={toggleTheme} className="grid h-8 w-8 place-items-center rounded-md border border-border bg-card hover:bg-elevated">
            {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
          </button>

          <div className="relative">
            <button onClick={() => setNotifOpen((o) => !o)} className="relative grid h-8 w-8 place-items-center rounded-md border border-border bg-card hover:bg-elevated">
              <Bell className="h-3.5 w-3.5" />
              <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-[color:var(--danger)]" />
            </button>
            {notifOpen && (
              <div className="absolute right-0 top-full z-30 mt-1 w-[min(20rem,calc(100vw-1rem))] rounded-md border border-border bg-popover p-2 text-sm">
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

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex items-center gap-2 rounded-md border border-border bg-card px-2 py-1 text-left hover:bg-elevated"
              >
            <div className="grid h-6 w-6 place-items-center rounded-full bg-[color:var(--brand)]/20 text-[10px] font-semibold text-[color:var(--brand)]">
              {user ? initials(user.full_name, user.email) : "?"}
            </div>
            <div className="hidden text-xs sm:block">
              <div className="font-medium leading-none">{user?.full_name ?? user?.email ?? "User"}</div>
              <div className="text-[10px] text-muted-foreground">
                {user ? roleLabel(user.role) : "—"}
                {user?.organisation ? ` · ${user.organisation.name}` : ""}
              </div>
            </div>
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              <DropdownMenuLabel className="space-y-1">
                <div className="truncate text-sm font-medium">{user?.full_name ?? user?.email ?? "User"}</div>
                <div className="truncate text-xs font-normal text-muted-foreground">{user?.email}</div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link
                  to="/login"
                  onClick={(event) => {
                    event.preventDefault();
                    void handleLogout();
                  }}
                  className="cursor-pointer text-muted-foreground"
                >
                  <LogOut className="h-4 w-4" />
                  Sign out
                </Link>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        <main className="mx-auto w-full max-w-[1440px] flex-1 p-3 sm:p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
