-- DEVELOPMENT_PLAN.md Finding F11 / docs/18. Known Bugs.md BUG-008.
--
-- quality_error_categories and quality_scan_runs both had a super_admin write
-- policy using `current_setting('app.role', true) = 'super_admin'` --
-- checking a Postgres session variable that is never set anywhere in this
-- codebase (grep confirms it appears nowhere else). Every other write-gating
-- policy in this schema uses `public.auth_user_role()`, which resolves the
-- caller's role by looking up their row in `public.users` via
-- `public.current_user_id()`. Because `app.role` is never set, the broken
-- policies could never be satisfied by any real request -- discovered while
-- auditing Workstream H (per-table role-coverage correctness, not just
-- policy existence).
--
-- Impact: quality_scan_runs is actively written by
-- POST /internal/quality-scan (backend/app/api/routes/quality.py,
-- require_role(SUPER_ADMIN)) through a normal request-scoped session. Once
-- Workstream I's SET LOCAL ROLE authenticated fix is deployed, that route
-- would start hard-failing for every super_admin, since the WITH CHECK could
-- never pass. quality_error_categories is not currently written by any app
-- code (a dormant reference/taxonomy table), so this half is lower-impact
-- today but still a bug worth fixing for the same reason.
--
-- NOTE: an earlier draft of this migration also planned to restrict both
-- tables' READ policies (qec_read / qsr_read, both `USING (true)`) to
-- super_admin only, on the assumption that DB-layer access should mirror the
-- app-layer route gating. That was wrong -- the original migration files
-- (20260624120000_error_taxonomy.sql, 20260624130000_quality_scan_runs.sql)
-- both explicitly comment "RLS: all roles can read; only super_admin can
-- write". World-readable SELECT is the documented, intentional design (both
-- are cross-org reference/taxonomy-style data, not per-client operational
-- data), not part of this bug. Only the write policies are touched here.

DROP POLICY IF EXISTS qec_super_admin_write ON quality_error_categories;
CREATE POLICY qec_super_admin_write ON quality_error_categories FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');

DROP POLICY IF EXISTS qsr_super_admin_write ON quality_scan_runs;
CREATE POLICY qsr_super_admin_write ON quality_scan_runs FOR ALL TO public
  USING (public.auth_user_role() = 'super_admin')
  WITH CHECK (public.auth_user_role() = 'super_admin');
