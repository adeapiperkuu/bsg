export type DeliverySite = "india" | "kosovo";

export type TeamRead = {
  id: string;
  project_id: string;
  org_id: string;
  name: string;
  site: DeliverySite;
  domain: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type AnnotatorRead = {
  id: string;
  org_id: string;
  team_id: string;
  full_name: string;
  site: DeliverySite;
  is_sme_certified: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};
