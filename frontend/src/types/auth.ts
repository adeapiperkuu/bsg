export type AppRole = "client" | "delivery_manager" | "bsg_leadership" | "super_admin";

export interface MePermissions {
  can_manage_projects: boolean;
  can_approve_communications: boolean;
  can_manage_metric_configurations: boolean;
  can_view_cross_client_portfolio: boolean;
  can_manage_users: boolean;
  can_manage_organisations: boolean;
}

export interface OrganisationSummary {
  id: string;
  name: string;
  vertical: string;
  region: string;
}

export interface MeUser {
  id: string;
  email: string;
  full_name: string | null;
  role: AppRole;
  org_id: string;
  is_active: boolean;
  organisation: OrganisationSummary | null;
  permissions: MePermissions;
}

export interface UserRead {
  id: string;
  org_id: string;
  email: string;
  full_name: string | null;
  role: AppRole;
  is_active: boolean;
}

export interface OrganisationRead {
  id: string;
  name: string;
  slug: string;
  vertical: string;
  region: string;
  is_active: boolean;
}

export interface AuthSession {
  id: string;
  email: string;
  full_name: string | null;
  role: AppRole;
}
