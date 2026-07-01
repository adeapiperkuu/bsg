import type { AppRole } from "@/types/auth";

const INTERNAL_WORKFORCE_READ_ROLES: ReadonlySet<AppRole> = new Set([
  "delivery_manager",
  "bsg_leadership",
  "super_admin",
]);

const WORKFORCE_MANAGE_ROLES: ReadonlySet<AppRole> = new Set(["delivery_manager", "super_admin"]);

export function canReadInternalWorkforce(role: AppRole | undefined): boolean {
  if (role === undefined) return false;
  return INTERNAL_WORKFORCE_READ_ROLES.has(role);
}

export function canManageWorkforce(role: AppRole | undefined): boolean {
  if (role === undefined) return false;
  return WORKFORCE_MANAGE_ROLES.has(role);
}
