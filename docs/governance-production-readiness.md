# Project Governance Production Readiness

Phase 8 hardens the Project Governance Agent for production use without changing the visible workflows.

## Access Control

- Read access remains limited to delivery managers, BSG leadership, super admins, and clients where existing project visibility allows it.
- Write access remains limited to delivery managers and super admins.
- Governance monitoring is restricted to BSG leadership and super admins.
- Super admins retain cross-organisation visibility where the governance services already support it.

## Audit Trail

Governance mutations now write append-only `audit_logs` events using the `governance.*` event namespace. Covered events include dependency, escalation, action, scope state, weekly summary, project charter, analytics export, and delivery-risk promotion changes.

Each event records the actor, source table, source row, previous values, new values, and metadata where available.

## Notifications

High-priority governance notifications are created for leadership-relevant changes:

- Blocking dependencies.
- Critical escalations.
- Scope states waiting for revision or approval.

Notifications reuse the existing notifications table and `SYSTEM` notification type so the feature does not require a schema-breaking enum change.

## AI Safety

The governance chatbot and generated artifacts continue to rely on approved governance evidence. Monitoring tracks empty or low-evidence answers so operators can detect evidence gaps and prompt quality issues.

## Monitoring

`GET /governance/monitoring?window_hours=24` returns operational counters for:

- Governance audit event volume.
- Governance chatbot query volume.
- Average and p95 chatbot latency.
- Empty or insufficient-evidence answers.
- Dashboard and charter exports.
- Most common recent governance event types.

## Exports

Analytics export endpoints are available for CSV and PDF:

- `GET /governance/analytics/export.csv`
- `GET /governance/analytics/export.pdf`

Exports are audited through the same governance audit trail.

## Performance

Phase 8 adds partial indexes for active governance records and monitoring paths:

- Dependencies by organisation, project, status, and due date.
- Escalations by organisation, project, status, severity, and raised date.
- Actions by organisation, project, status, due date, and completion date.
- Scope states by organisation, project, and status.
- Project charters by organisation, project, status, and created date.
- Governance chatbot queries by organisation, agent, and created date.
- Governance audit logs by organisation and created date.

## Remaining Opportunities

- Move heavy AI generation to background jobs with retry/dead-letter visibility.
- Add first-class notification priority/archive columns if the notification schema evolves.
- Add Slack/email delivery adapters for critical governance notifications.
- Add server-side Excel exports if executive users require workbook formatting.
- Add synthetic monitoring for `/governance`, `/governance/bootstrap`, and chatbot latency.
