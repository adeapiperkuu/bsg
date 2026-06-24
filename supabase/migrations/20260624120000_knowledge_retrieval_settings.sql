-- Org-level retrieval settings for the Operational Knowledge Agent.

CREATE TABLE IF NOT EXISTS public.knowledge_retrieval_settings (
  org_id uuid PRIMARY KEY REFERENCES public.organisations(id) ON DELETE CASCADE,
  only_approved boolean NOT NULL DEFAULT true,
  include_histories boolean NOT NULL DEFAULT true,
  min_confidence double precision NOT NULL DEFAULT 0.25,
  max_sources integer NOT NULL DEFAULT 5 CHECK (max_sources >= 1 AND max_sources <= 10),
  project text,
  department text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.knowledge_retrieval_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_retrieval_settings_select ON public.knowledge_retrieval_settings
  FOR SELECT USING (org_id = public.auth_user_org_id());

CREATE POLICY knowledge_retrieval_settings_manage ON public.knowledge_retrieval_settings
  FOR ALL USING (
    public.auth_user_role() IN ('super_admin', 'bsg_leadership')
    AND org_id = public.auth_user_org_id()
  );
