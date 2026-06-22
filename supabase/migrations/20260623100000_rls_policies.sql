-- RLS policies for Operations Tower (Phase 1)
-- Uses request.jwt.claims.sub set by the FastAPI backend per request.

CREATE OR REPLACE FUNCTION public.current_user_id() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('request.jwt.claims', true)::json->>'sub', '')::uuid
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION public.auth_user_role() RETURNS app_role AS $$
  SELECT role FROM public.users WHERE id = public.current_user_id()
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION public.auth_user_org_id() RETURNS uuid AS $$
  SELECT org_id FROM public.users WHERE id = public.current_user_id()
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

-- organisations
CREATE POLICY organisations_client_select ON organisations FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND id = public.auth_user_org_id());
CREATE POLICY organisations_dm_select ON organisations FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND id = public.auth_user_org_id());
CREATE POLICY organisations_leadership_select ON organisations FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY organisations_super_admin_all ON organisations FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

-- users
CREATE POLICY users_client_select ON users FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND id = public.current_user_id());
CREATE POLICY users_dm_select ON users FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY users_leadership_select ON users FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY users_super_admin_all ON users FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

-- org-scoped read for client
CREATE POLICY client_org_read ON projects FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id() AND deleted_at IS NULL);
CREATE POLICY dm_org_all ON projects FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY leadership_org_read ON projects FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY super_admin_org_read ON projects FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin' AND deleted_at IS NULL);

-- milestones (via org_id)
CREATE POLICY milestones_client_select ON milestones FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id() AND deleted_at IS NULL);
CREATE POLICY milestones_dm_all ON milestones FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY milestones_leadership_select ON milestones FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY milestones_super_admin_select ON milestones FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin' AND deleted_at IS NULL);

-- throughput_snapshots
CREATE POLICY throughput_client_select ON throughput_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY throughput_dm_all ON throughput_snapshots FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY throughput_leadership_select ON throughput_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY throughput_super_admin_select ON throughput_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- teams (client read own org; no annotator for client per spec)
CREATE POLICY teams_client_select ON teams FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id() AND deleted_at IS NULL);
CREATE POLICY teams_dm_all ON teams FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY teams_leadership_select ON teams FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY teams_super_admin_select ON teams FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin' AND deleted_at IS NULL);

-- annotators (no client access)
CREATE POLICY annotators_dm_all ON annotators FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY annotators_leadership_select ON annotators FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership' AND deleted_at IS NULL);
CREATE POLICY annotators_super_admin_select ON annotators FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin' AND deleted_at IS NULL);

-- quality_snapshots
CREATE POLICY quality_snapshots_client_select ON quality_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY quality_snapshots_dm_all ON quality_snapshots FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY quality_snapshots_leadership_select ON quality_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY quality_snapshots_super_admin_select ON quality_snapshots FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- quality_error_entries
CREATE POLICY quality_errors_client_select ON quality_error_entries FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY quality_errors_dm_all ON quality_error_entries FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY quality_errors_leadership_select ON quality_error_entries FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY quality_errors_super_admin_select ON quality_error_entries FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- risk_alerts
CREATE POLICY risk_alerts_client_select ON risk_alerts FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY risk_alerts_dm_all ON risk_alerts FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY risk_alerts_leadership_select ON risk_alerts FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY risk_alerts_super_admin_select ON risk_alerts FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- bottlenecks
CREATE POLICY bottlenecks_client_select ON bottlenecks FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY bottlenecks_dm_all ON bottlenecks FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY bottlenecks_leadership_select ON bottlenecks FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY bottlenecks_super_admin_select ON bottlenecks FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- client_communications
CREATE POLICY comms_client_select ON client_communications FOR SELECT TO public
  USING (
    public.auth_user_role() = 'client'
    AND org_id = public.auth_user_org_id()
    AND status = 'sent'
  );
CREATE POLICY comms_dm_all ON client_communications FOR ALL TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id())
  WITH CHECK (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY comms_leadership_select ON client_communications FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY comms_super_admin_select ON client_communications FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- communication_evidence_links (mirror comms org scope via join would be complex; use org_id on link table)
CREATE POLICY comm_evidence_client_select ON communication_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY comm_evidence_dm_select ON communication_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY comm_evidence_leadership_select ON communication_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY comm_evidence_super_admin_select ON communication_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- agent_queries
CREATE POLICY agent_queries_client_select ON agent_queries FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id() AND user_id = public.current_user_id());
CREATE POLICY agent_queries_dm_select ON agent_queries FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY agent_queries_leadership_select ON agent_queries FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY agent_queries_super_admin_select ON agent_queries FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');
CREATE POLICY agent_queries_insert ON agent_queries FOR INSERT TO public
  WITH CHECK (user_id = public.current_user_id() AND org_id = public.auth_user_org_id());

-- agent_query_evidence_links
CREATE POLICY agent_evidence_client_select ON agent_query_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY agent_evidence_dm_select ON agent_query_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY agent_evidence_leadership_select ON agent_query_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY agent_evidence_super_admin_select ON agent_query_evidence_links FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- client_csat_scores
CREATE POLICY csat_client_all ON client_csat_scores FOR ALL TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id() AND submitted_by = public.current_user_id())
  WITH CHECK (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id() AND submitted_by = public.current_user_id());
CREATE POLICY csat_dm_select ON client_csat_scores FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY csat_leadership_select ON client_csat_scores FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY csat_super_admin_select ON client_csat_scores FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- metric_configurations
CREATE POLICY metrics_read ON metric_configurations FOR SELECT TO public
  USING (public.current_user_id() IS NOT NULL AND deleted_at IS NULL);
CREATE POLICY metrics_super_admin_write ON metric_configurations FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin') WITH CHECK (public.auth_user_role() = 'super_admin');

-- delivery_confidence_scores
CREATE POLICY confidence_client_select ON delivery_confidence_scores FOR SELECT TO public
  USING (public.auth_user_role() = 'client' AND org_id = public.auth_user_org_id());
CREATE POLICY confidence_dm_select ON delivery_confidence_scores FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());
CREATE POLICY confidence_leadership_select ON delivery_confidence_scores FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');
CREATE POLICY confidence_super_admin_select ON delivery_confidence_scores FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- notifications (own only)
CREATE POLICY notifications_own ON notifications FOR ALL TO public
  USING (user_id = public.current_user_id()) WITH CHECK (user_id = public.current_user_id());
