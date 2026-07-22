-- Repair: replace dead app.current_org_id policies with auth_user_* JWT helpers.
-- Safe to run if 20260722120000 was already applied with the broken policies.

DROP POLICY IF EXISTS client_report_schedules_org_isolation
  ON client_report_schedules;
DROP POLICY IF EXISTS client_intelligence_report_packages_org_isolation
  ON client_intelligence_report_packages;
DROP POLICY IF EXISTS client_intelligence_report_approvals_org_isolation
  ON client_intelligence_report_approvals;
DROP POLICY IF EXISTS client_intelligence_report_deliveries_org_isolation
  ON client_intelligence_report_deliveries;

-- Idempotent recreate (in case this repair re-runs after a partial apply).
DROP POLICY IF EXISTS client_report_schedules_dm_all
  ON client_report_schedules;
DROP POLICY IF EXISTS client_report_schedules_leadership_select
  ON client_report_schedules;
DROP POLICY IF EXISTS client_report_schedules_super_admin_all
  ON client_report_schedules;
DROP POLICY IF EXISTS client_intelligence_report_packages_dm_all
  ON client_intelligence_report_packages;
DROP POLICY IF EXISTS client_intelligence_report_packages_leadership_select
  ON client_intelligence_report_packages;
DROP POLICY IF EXISTS client_intelligence_report_packages_leadership_all
  ON client_intelligence_report_packages;
DROP POLICY IF EXISTS client_intelligence_report_packages_super_admin_all
  ON client_intelligence_report_packages;
DROP POLICY IF EXISTS client_intelligence_report_approvals_dm_all
  ON client_intelligence_report_approvals;
DROP POLICY IF EXISTS client_intelligence_report_approvals_leadership_select
  ON client_intelligence_report_approvals;
DROP POLICY IF EXISTS client_intelligence_report_approvals_leadership_all
  ON client_intelligence_report_approvals;
DROP POLICY IF EXISTS client_intelligence_report_approvals_super_admin_all
  ON client_intelligence_report_approvals;
DROP POLICY IF EXISTS client_intelligence_report_deliveries_dm_all
  ON client_intelligence_report_deliveries;
DROP POLICY IF EXISTS client_intelligence_report_deliveries_leadership_select
  ON client_intelligence_report_deliveries;
DROP POLICY IF EXISTS client_intelligence_report_deliveries_super_admin_all
  ON client_intelligence_report_deliveries;

CREATE POLICY client_report_schedules_dm_all
  ON client_report_schedules
  FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_report_schedules_leadership_select
  ON client_report_schedules
  FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY client_report_schedules_super_admin_all
  ON client_report_schedules
  FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY client_intelligence_report_packages_dm_all
  ON client_intelligence_report_packages
  FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_report_packages_leadership_all
  ON client_intelligence_report_packages
  FOR ALL TO public
  USING (public.auth_user_role() = 'bsg_leadership')
  WITH CHECK (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY client_intelligence_report_packages_super_admin_all
  ON client_intelligence_report_packages
  FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY client_intelligence_report_approvals_dm_all
  ON client_intelligence_report_approvals
  FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_report_approvals_leadership_all
  ON client_intelligence_report_approvals
  FOR ALL TO public
  USING (public.auth_user_role() = 'bsg_leadership')
  WITH CHECK (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY client_intelligence_report_approvals_super_admin_all
  ON client_intelligence_report_approvals
  FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

CREATE POLICY client_intelligence_report_deliveries_dm_all
  ON client_intelligence_report_deliveries
  FOR ALL TO public
  USING (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  )
  WITH CHECK (
    public.auth_user_role() = 'delivery_manager'
    AND org_id = public.auth_user_org_id()
  );

CREATE POLICY client_intelligence_report_deliveries_leadership_select
  ON client_intelligence_report_deliveries
  FOR SELECT TO public
  USING (public.auth_user_role() = 'bsg_leadership');

CREATE POLICY client_intelligence_report_deliveries_super_admin_all
  ON client_intelligence_report_deliveries
  FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
