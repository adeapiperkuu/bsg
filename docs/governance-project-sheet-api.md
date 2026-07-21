# Governance Project Sheet API

## Endpoint

```http
GET /governance/project-sheet/{project_id}
```

The endpoint is the bounded initial read model for the Governance project drawer. It does not
replace the individual list, filtering, pagination, export, mutation, charter, recommendation, or
audit endpoints.

## Response

```json
{
  "data": {
    "project": {
      "id": "00000000-0000-0000-0000-000000000001",
      "name": "Example Project",
      "description": "Concise project description",
      "vertical": "Example Vertical",
      "status": "active",
      "start_date": "2026-01-01",
      "target_end_date": "2026-12-31"
    },
    "summary": {
      "scope_status": "approved",
      "scope_version": "v2",
      "open_dependencies": 3,
      "blocking_dependencies": 1,
      "overdue_actions": 0,
      "open_actions": 2,
      "open_escalations": 1,
      "critical_escalations": 0,
      "health": "amber"
    },
    "scope": null,
    "dependencies": { "items": [], "total": 3, "has_more": false },
    "actions": { "items": [], "total": 2, "has_more": false },
    "escalations": { "items": [], "total": 1, "has_more": false },
    "delivery_risks": { "items": [], "total": 0, "has_more": false },
    "permissions": {
      "can_write": true,
      "can_view_internal": true,
      "can_view_delivery_risks": true
    },
    "generated_at": "2026-07-14T12:00:00Z"
  }
}
```

Each list is limited to six rows. `total` is the authorized total for that section and `has_more`
signals that the UI should offer the full project-filtered list.

## Authorization

- Super administrators use existing cross-organization project visibility.
- Delivery managers and BSG leadership are restricted to their organization.
- Clients require an active assignment to the requested project.
- Dependencies, actions, full scope details, and scope notes are internal-only.
- Authorized clients receive only published `client_visible` escalations. Their descriptions use
  the approved client summary, and internal source/assignee fields are removed.
- Delivery-risk rows are returned only to delivery managers and super administrators, matching the
  existing promotion control.
- Missing projects return the standard 404 response. Existing but unauthorized projects return the
  standard 403 response.

## Query behavior

An authorized success uses one database execute containing project authorization, project metadata,
summary/counts, and every bounded list section. A denied or missing request uses a second existence
check to retain the existing error distinction. The endpoint has no process-local cache in Phase E.

The individual APIs remain authoritative for full sections:

- `GET /governance/dependencies?project_id=...`
- `GET /governance/actions?project_id=...`
- `GET /governance/escalations?project_id=...`
- `GET /governance/scope-states?project_id=...`
- `GET /projects/{project_id}/risk-alerts`
