import { useContext } from "react";

import { RoleContext } from "@/lib/bsg/role-context";

export function useRole() {
  const ctx = useContext(RoleContext);
  if (!ctx) throw new Error("useRole must be used inside RoleProvider");
  return ctx;
}
