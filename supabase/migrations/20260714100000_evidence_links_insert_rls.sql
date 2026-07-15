-- DEVELOPMENT_PLAN.md Finding F10 / docs/18. Known Bugs.md BUG-007: both
-- evidence-link tables have RLS enabled and a full SELECT policy set but no
-- INSERT policy at all, in any migration -- confirmed live 2026-07-14 via
-- backend/tests/rls/test_role_visibility.py. Postgres default-denies INSERT
-- for every role on an RLS-enabled table with no matching policy, same
-- failure mode as BUG-003 (audit_logs). Currently masked by BUG-001
-- (BYPASSRLS), but create_draft() (backend/app/services/communications.py)
-- and any agent logging an evidence-backed agent_queries row both insert
-- through non-bypass, request-scoped sessions today.
--
-- Mirrors the existing comm_evidence_dm_select / agent_evidence_dm_select
-- SELECT policies' join logic: any authenticated role may insert evidence
-- for a parent row in their own org -- same broad-creation/narrow-read
-- pattern already used for audit_logs and comms_dm_all.

CREATE POLICY comm_evidence_insert ON communication_evidence_links FOR INSERT TO public
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.client_communications cc
      WHERE cc.id = communication_evidence_links.communication_id
        AND cc.org_id = public.auth_user_org_id()
    )
  );

CREATE POLICY agent_evidence_insert ON agent_query_evidence_links FOR INSERT TO public
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.agent_queries aq
      WHERE aq.id = agent_query_evidence_links.agent_query_id
        AND aq.org_id = public.auth_user_org_id()
    )
  );
