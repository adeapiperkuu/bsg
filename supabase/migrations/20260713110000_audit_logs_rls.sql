-- Workstream B (DEVELOPMENT_PLAN.md): fix the audit_logs write path.
--
-- Problem: 20260624120000_audit_logs.sql enables RLS on audit_logs but never
-- adds a single CREATE POLICY for it -- confirmed as the only such gap across
-- all 67 RLS-enabled tables in this repo (see the lint added alongside this
-- migration, backend/tests/test_migrations_rls_policy_coverage.py). Postgres
-- default-denies every operation on an RLS-enabled table with no matching
-- policy, so every write through AuditLogger.log()
-- (backend/app/agents/delivery/audit/audit_logger.py) and log_governance_event()
-- (backend/app/agents/governance/services/audit_service.py) -- both of which
-- write through the caller's own request-scoped, RLS-bound session, not
-- service_role -- would fail wherever RLS is actually enforced.
--
-- Access model: audit_logs has no user_id column (a separate, smaller gap
-- noted in the plan but not fixed here -- see DEVELOPMENT_PLAN.md), so
-- policies are scoped by org_id only. Confirmed call sites span all four
-- roles: client (governance analytics CSV/PDF export -- see READ_ROLES in
-- backend/app/agents/governance/routes/governance.py), delivery_manager and
-- super_admin (backend/app/api/routes/delivery.py; governance WRITE_ROLES),
-- and bsg_leadership (governance MONITORING_ROLES). So INSERT is granted to
-- any authenticated role for their own org, matching the pattern the docs
-- already use for evidence-link tables (client_communications,
-- agent_query_evidence_links etc.), where creation is broader than read.
-- Read access follows the narrower, documented audit-export model
-- (13. Security & Compliance.md SS11.4: delivery_manager + super_admin),
-- plus bsg_leadership per its usual all-org read-only pattern. No read
-- policy is added for 'client' -- there is no current route that exposes
-- audit_logs to client users, and the security doc's audit-export access
-- list does not include them.

CREATE POLICY audit_logs_insert ON audit_logs FOR INSERT TO public
  WITH CHECK (org_id = public.auth_user_org_id());

CREATE POLICY audit_logs_dm_select ON audit_logs FOR SELECT TO public
  USING (public.auth_user_role() = 'delivery_manager' AND org_id = public.auth_user_org_id());

CREATE POLICY audit_logs_leadership_select ON audit_logs FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY audit_logs_super_admin_select ON audit_logs FOR SELECT TO public
  USING (public.auth_user_role() = 'super_admin');

-- No UPDATE/DELETE policies: audit_logs is append-only, same as agent_queries
-- (13. Security & Compliance.md SS11.3). Default-deny is correct here.
