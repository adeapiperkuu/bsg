import { useEffect, useState, type ReactNode } from "react";

import { RoleContext, type Role, type Theme } from "@/lib/bsg/role-context";

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>("Delivery Manager");
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.classList.toggle("light", theme === "light");
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <RoleContext.Provider
      value={{
        role,
        setRole,
        theme,
        toggleTheme: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
      }}
    >
      {children}
    </RoleContext.Provider>
  );
}
