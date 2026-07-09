import type { AnnotatorRead, TeamRead } from "@/types/workforce";

export const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
export const ORG_ID = "22222222-2222-4222-8222-222222222222";
export const TEAM_A_ID = "33333333-3333-4333-8333-333333333333";
export const TEAM_B_ID = "44444444-4444-4444-8444-444444444444";
export const ANNOTATOR_ID = "55555555-5555-4555-8555-555555555555";

const TIMESTAMP = "2026-01-15T10:00:00.000Z";

export function makeTeam(overrides: Partial<TeamRead> = {}): TeamRead {
  return {
    id: TEAM_A_ID,
    project_id: PROJECT_ID,
    org_id: ORG_ID,
    name: "Alpha Team",
    site: "india",
    domain: "Life Sciences",
    is_active: true,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    ...overrides,
  };
}

export function makeTeamB(overrides: Partial<TeamRead> = {}): TeamRead {
  return makeTeam({
    id: TEAM_B_ID,
    name: "Bravo Team",
    site: "kosovo",
    domain: "Finance",
    ...overrides,
  });
}

export function makeAnnotator(overrides: Partial<AnnotatorRead> = {}): AnnotatorRead {
  return {
    id: ANNOTATOR_ID,
    org_id: ORG_ID,
    team_id: TEAM_A_ID,
    full_name: "Jane Doe",
    site: "india",
    is_sme_certified: false,
    is_active: true,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    ...overrides,
  };
}
