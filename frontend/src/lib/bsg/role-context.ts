import { createContext } from "react";

export type Role = "Delivery Manager" | "Client" | "BSG Leadership";
export type Theme = "dark" | "light";

type Ctx = {
  role: Role;
  setRole: (r: Role) => void;
  theme: Theme;
  toggleTheme: () => void;
};

export const RoleContext = createContext<Ctx | null>(null);
