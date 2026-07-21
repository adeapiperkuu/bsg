import {
  Activity,
  BookOpen,
  Bot,
  Briefcase,
  Building2,
  Crown,
  FileText,
  FolderKanban,
  GitBranch,
  LayoutDashboard,
  Settings2,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { ComponentType } from "react";

import type { AppRole, MeUser } from "@/types/auth";

type NavItem = {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
};

type NavSection = { section: string; items: NavItem[] };

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
      { to: "/teams", label: "Teams", icon: Users },
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
      { to: "/client", label: "My Projects", icon: LayoutDashboard },
      { to: "/client/status", label: "Delivery Status", icon: Activity },
      { to: "/client/reports", label: "Reports", icon: FileText },
      { to: "/client/ask", label: "Ask Agent", icon: BookOpen },
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
