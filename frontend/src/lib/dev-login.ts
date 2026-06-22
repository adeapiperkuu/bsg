import type { AppRole } from "@/types/auth";

export type DevLoginAccount = {
  label: string;
  email: string;
  password: string;
  role: AppRole;
};

export const DEV_LOGIN_PASSWORD = "bsg-dev-2026";

export const DEV_LOGIN_ACCOUNTS: DevLoginAccount[] = [
  {
    label: "Admin",
    email: "admin@bsg.dev",
    password: DEV_LOGIN_PASSWORD,
    role: "super_admin",
  },
  {
    label: "PM",
    email: "pm@bsg.dev",
    password: DEV_LOGIN_PASSWORD,
    role: "delivery_manager",
  },
  {
    label: "Client",
    email: "client@bsg.dev",
    password: DEV_LOGIN_PASSWORD,
    role: "client",
  },
];

export const isDevLoginEnabled = import.meta.env.DEV;
