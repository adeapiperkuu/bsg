-- Workstream A (DEVELOPMENT_PLAN.md): enforce project-assignment scoping for the
-- `client` role at the RLS layer, not only in application code.
--
-- Problem: backend/app/services/scoping.py already restricts `client` users to
-- projects they have an active `project_assignments` row for, but every
-- `client`-role RLS policy written in 20260623100000_rls_policies.sql only
-- checks org_id. RLS is supposed to be the authoritative, defence-in-depth
-- layer (13. Security & Compliance.md, Rule 1) -- right now it is *more*
-- permissive than the application layer for this specific boundary, which
-- defeats the purpose of having it. This migration closes that gap.
--
-- Assumption (flagged for product/security sign-off per plan Workstream A
-- step 1): project-assignment scoping applies to every `client` user, with
-- no per-organisation opt-out. This matches the current, unconditional
-- behaviour of scoping.py -- there is no toggle in the app layer today, so
-- this migration does not introduce a new restriction, it only makes an
-- existing one enforceable at the database layer as well.
--
-- Separately, while rewriting the client-role policies on
-- communication_evidence_links and agent_query_evidence_links, this
-- migration also fixes a pre-existing bug: 20260623100000_rls_policies.sql
-- has both tables' client/delivery_manager SELECT policies reference an
-- `org_id` column that was never added to either table (see the CREATE
-- TABLE statements in 20260622090000_initial_backend_schema.sql). As written,
-- those four CREATE POLICY statements cannot succeed -- "column org_id does
-- not exist" -- which would abort the entire rls_policies.sql migration in
-- any environment where migrations run inside a transaction. This migration
-- replaces those four policies with ones that join through the parent table
-- (client_communications / agent_queries) instead of a non-existent column.

CREATE OR REPLACE FUNCTION public.client_has_project_access(p_project_id uuid) RETURNS boolean AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.project_assignments pa
    WHERE pa.project_id = p_project_id
      AND pa.user_id = public.current_user_id()
      AND pa.is_active
      AND pa.deleted_at IS NULL
  )
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

-- projects
DROP POLICY IF EXISTS client_org_read ON projects;
CREATE POLICY client_org_read ON projects FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND deleted_at IS NULL
    AND public.client_has_project_access(id)
  );

-- milestones
DROP POLICY IF EXISTS milestones_client_select ON milestones;
CREATE POLICY milestones_client_select ON milestones FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND deleted_at IS NULL
    AND public.client_has_project_access(project_id)
  );

-- throughput_snapshots
DROP POLICY IF EXISTS throughput_client_select ON throughput_snapshots;
CREATE POLICY throughput_client_select ON throughput_snapshots FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND public.client_has_project_access(project_id)
  );

-- teams
DROP POLICY IF EXISTS teams_client_select ON teams;
CREATE POLICY teams_client_select ON teams FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND deleted_at IS NULL
    AND public.client_has_project_access(project_id)
  );

-- quality_snapshots
DROP POLICY IF EXISTS quality_snapshots_client_select ON quality_snapshots;
CREATE POLICY quality_snapshots_client_select ON quality_snapshots FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND public.client_has_project_access(project_id)
  );

-- quality_error_entries (no project_id column -- reached via quality_snapshot_id)
DROP POLICY IF EXISTS quality_errors_client_select ON quality_error_entries;
CREATE POLICY quality_errors_client_select ON quality_error_entries FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND EXISTS (
      SELECT 1 FROM public.quality_snapshots qs
      WHERE qs.id = quality_error_entries.quality_snapshot_id
        AND public.client_has_project_access(qs.project_id)
    )
  );

-- risk_alerts
DROP POLICY IF EXISTS risk_alerts_client_select ON risk_alerts;
CREATE POLICY risk_alerts_client_select ON risk_alerts FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND public.client_has_project_access(project_id)
  );

-- bottlenecks
DROP POLICY IF EXISTS bottlenecks_client_select ON bottlenecks;
CREATE POLICY bottlenecks_client_select ON bottlenecks FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND public.client_has_project_access(project_id)
  );

-- client_communications
DROP POLICY IF EXISTS comms_client_select ON client_communications;
CREATE POLICY comms_client_select ON client_communications FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND status = 'sent'
    AND public.client_has_project_access(project_id)
  );

-- communication_evidence_links: no org_id column on this table at all (bug fix,
-- see header) -- reached via communication_id -> client_communications.
DROP POLICY IF EXISTS comm_evidence_client_select ON communication_evidence_links;
CREATE POLICY comm_evidence_client_select ON communication_evidence_links FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND EXISTS (
      SELECT 1 FROM public.client_communications cc
      WHERE cc.id = communication_evidence_links.communication_id
        AND cc.org_id = public.auth_user_org_id()
        AND cc.status = 'sent'
        AND public.client_has_project_access(cc.project_id)
    )
  );

DROP POLICY IF EXISTS comm_evidence_dm_select ON communication_evidence_links;
CREATE POLICY comm_evidence_dm_select ON communication_evidence_links FOR SELECT TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND EXISTS (
      SELECT 1 FROM public.client_communications cc
      WHERE cc.id = communication_evidence_links.communication_id
        AND cc.org_id = public.auth_user_org_id()
    )
  );

-- agent_queries: project_id is nullable (NULL = cross-project query, per
-- 10. DB Schema.md). A client's own cross-project query stays visible; a
-- project-scoped query is only visible if they're still assigned to it.
DROP POLICY IF EXISTS agent_queries_client_select ON agent_queries;
CREATE POLICY agent_queries_client_select ON agent_queries FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND user_id = public.current_user_id()
    AND (project_id IS NULL OR public.client_has_project_access(project_id))
  );

-- agent_query_evidence_links: no org_id column on this table at all (bug fix,
-- see header) -- reached via agent_query_id -> agent_queries.
DROP POLICY IF EXISTS agent_evidence_client_select ON agent_query_evidence_links;
CREATE POLICY agent_evidence_client_select ON agent_query_evidence_links FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND EXISTS (
      SELECT 1 FROM public.agent_queries aq
      WHERE aq.id = agent_query_evidence_links.agent_query_id
        AND aq.org_id = public.auth_user_org_id()
        AND aq.user_id = public.current_user_id()
        AND (aq.project_id IS NULL OR public.client_has_project_access(aq.project_id))
    )
  );

DROP POLICY IF EXISTS agent_evidence_dm_select ON agent_query_evidence_links;
CREATE POLICY agent_evidence_dm_select ON agent_query_evidence_links FOR SELECT TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND EXISTS (
      SELECT 1 FROM public.agent_queries aq
      WHERE aq.id = agent_query_evidence_links.agent_query_id
        AND aq.org_id = public.auth_user_org_id()
    )
  );

-- delivery_confidence_scores
DROP POLICY IF EXISTS confidence_client_select ON delivery_confidence_scores;
CREATE POLICY confidence_client_select ON delivery_confidence_scores FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND public.client_has_project_access(project_id)
  );
