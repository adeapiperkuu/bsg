import {
  Activity,
  Bell,
  BookOpen,
  Bot,
  Briefcase,
  Building2,
  CalendarDays,
  ClipboardCheck,
  Crown,
  FileCheck2,
  FileText,
  FolderOpen,
  FolderKanban,
  GitBranch,
  GitPullRequest,
  LayoutDashboard,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import type { ComponentType } from "react";

import type { AppRole, MeUser } from "@/types/auth";

export type ClientWorkspaceView =
  | "overview"
  | "progress"
  | "risks"
  | "actions"
  | "summary"
  | "documents"
  | "deliverables"
  | "changes"
  | "meetings"
  | "notifications";

export type NavItem = {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  view?: ClientWorkspaceView;
};

export type NavSection = { section: string; items: NavItem[] };

const internalNav: NavSection[] = [
  {
    section: "Agents",
    items: [
      { to: "/dashboard", label: "Operational Tower", icon: LayoutDashboard },
      { to: "/delivery", label: "Delivery Performance", icon: Activity },
      { to: "/quality", label: "Quality Intelligence", icon: ShieldCheck },
      { to: "/workforce", label: "Workforce & Capability", icon: Users },
      { to: "/governance", label: "Project Governance", icon: GitBranch },
      { to: "/client-intelligence", label: "Client Intelligence", icon: Briefcase },
    ],
  },
  {
    section: "Workspace",
    items: [
      { to: "/knowledge", label: "Knowledge Agent", icon: BookOpen },
      { to: "/projects", label: "Projects", icon: FolderKanban },
    ],
  },
  {
    section: "Reporting",
    items: [{ to: "/reports", label: "Reports", icon: FileText }],
  },
];

const clientNav: NavSection[] = [
  {
    section: "Client Portal",
    items: [
      { to: "/client/status", label: "Overview", icon: LayoutDashboard, view: "overview" },
      { to: "/client/status", label: "Progress", icon: Target, view: "progress" },
      { to: "/client/status", label: "Risks & issues", icon: ShieldAlert, view: "risks" },
      { to: "/client/status", label: "Your actions", icon: ClipboardCheck, view: "actions" },
      { to: "/client/status", label: "AI summary", icon: Sparkles, view: "summary" },
      { to: "/client/status", label: "Documents", icon: FolderOpen, view: "documents" },
      { to: "/client/status", label: "Deliverables", icon: FileCheck2, view: "deliverables" },
      { to: "/client/status", label: "Change requests", icon: GitPullRequest, view: "changes" },
      { to: "/client/status", label: "Meetings", icon: CalendarDays, view: "meetings" },
      { to: "/client/status", label: "Notifications", icon: Bell, view: "notifications" },
      { to: "/client/reports", label: "Reports", icon: FileText },
      { to: "/client/ask", label: "Ask AI", icon: Bot },
    ],
  },
];

const leadershipNav: NavSection[] = [
  {
    section: "Portfolio",
    items: [
      { to: "/leadership", label: "Leadership Cockpit", icon: Crown },
      { to: "/client-intelligence", label: "Client Intelligence", icon: Briefcase },
    ],
  },
];

const adminNav: NavSection[] = [
  {
    section: "Platform",
    items: [
      { to: "/admin", label: "Admin Console", icon: Settings2 },
      { to: "/admin/users", label: "Users", icon: Users },
      { to: "/admin/organisations", label: "Organisations", icon: Building2 },
      { to: "/admin/projects", label: "Projects", icon: FolderKanban },
      { to: "/admin/agent-runs", label: "Agent Runs", icon: Bot },
      { to: "/client-intelligence", label: "Client Intelligence", icon: Briefcase },
    ],
  },
];

export const allNavigationSections = [...internalNav, ...clientNav, ...leadershipNav, ...adminNav];

export function navForUser(user: MeUser | null): NavSection[] {
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
