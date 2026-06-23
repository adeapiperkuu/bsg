import type { AppRole } from "@/types/auth";

export const USERS_PER_PAGE = 12;
export const roles: AppRole[] = ["client", "delivery_manager", "bsg_leadership", "super_admin"];
export const editControlClass =
  "h-10 rounded-md border border-input bg-background px-3 text-sm shadow-none transition-colors focus:outline-none focus:ring-1 focus:ring-ring";
export const toolbarIconButtonClass =
  "h-9 w-9 rounded-full border border-[color:var(--brand)] bg-[color:var(--brand)] text-[color:var(--brand-foreground)] shadow-none transition-colors hover:bg-[color:var(--brand)]/90 hover:text-[color:var(--brand-foreground)]";

export function formatRole(role: AppRole): string {
  return role
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function visiblePages(currentPage: number, totalPages: number): number[] {
  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  return [...pages].filter((page) => page >= 1 && page <= totalPages).sort((a, b) => a - b);
}

export function initials(name: string | null, email: string): string {
  if (name) {
    const parts = name.trim().split(/\s+/);
    return parts.slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
  }
  return email[0]?.toUpperCase() ?? "?";
}
