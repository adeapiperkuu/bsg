import type { AppRole } from "@/types/auth";

export function roleLabel(role: AppRole): string {
  switch (role) {
    case "client":
      return "Client";
    case "delivery_manager":
      return "Delivery Manager";
    case "bsg_leadership":
      return "BSG Leadership";
    case "super_admin":
      return "Super Admin";
    default:
      return role;
  }
}
