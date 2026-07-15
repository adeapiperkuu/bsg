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

/** DEVELOPMENT_PLAN.md Workstream E. Returned by POST /auth/login instead of
 * AuthSession when the role requires MFA and the session isn't at aal2 yet.
 * `pending_token` is a short-lived bearer token for the /auth/mfa/* calls
 * only -- never store it as the persistent session. */
export interface MfaRequired {
  mfa_required: true;
  stage: "enroll" | "challenge";
  pending_token: string;
  factor_id: string | null;
}

export interface MfaEnrollResult {
  factor_id: string;
  qr_code: string;
  secret: string;
}

export interface MfaChallengeResult {
  factor_id: string;
  challenge_id: string;
}

export type LoginResult =
  | { status: "success"; session: AuthSession }
  | ({ status: "mfa_required" } & MfaRequired);
