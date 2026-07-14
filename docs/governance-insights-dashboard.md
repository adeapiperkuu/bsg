# Governance Insights Dashboard (Phase 11)

Portfolio-level executive visibility into governance health, trends, recurring risks, and recommendation outcomes. Distinct from Knowledge Continuous Learning (also labeled Phase 11 in knowledge docs).

## Surfaces

- Backend: additive fields on existing analytics summary/detail/export APIs
- Frontend: expanded **Executive Governance Intelligence** section on `/governance`
- No dedicated `/governance/insights` route
- No new migrations (aggregates from existing tables)

## Architecture

```
Filters (days, project_id, vertical)
  → GET /governance/analytics/summary   (lean header)
  → GET /governance/analytics/detail    (trends, rates, lists, heatmap)
  → merge on client
  → Executive dashboard (KPIs, charts, tables, drill-down)
  → GET /governance/analytics/export.{csv|pdf}
```

## Scores

| Score | Definition |
|-------|------------|
| Project governance score | Existing penalty model from open blockers, escalations, overdue actions, pending scope, delivery signals (0–100) |
| Portfolio governance score | Mean of filtered project scores |
| Risk levels | `excellent` ≥90, `healthy` ≥75, `moderate_risk` ≥60, `high_risk` ≥40, else `critical` |

Department filter maps to `Project.vertical` (projects have no separate `department` column).

## Insights KPIs

| KPI | Source |
|-----|--------|
| `portfolio_governance_score` | Summary + detail |
| `projects_at_risk` | Count of high_risk/critical projects |
| `recommendation_acceptance_rate_pct` | Detail — accepted / created in window |
| `recommendation_dismissal_rate_pct` | Detail — dismissed / created in window |
| `escalations_created` | Detail — daily trend sum |
| `recommendations_created` | Detail — AI recommendation rows in window |
| `sla_adherence_pct` | Detail — action SLA helper |

Acceptance includes `partially_accepted`, `accepted_as_action`, `accepted_as_escalation`, or `accepted_at` set.

Summary only populates portfolio score + projects at risk (keeps first-paint lean). Detail fills rates and lists.

## Detail lists & heatmap

- `top_governance_risks`
- `top_recurring_blockers` (blocking dependency types)
- `top_recurring_mitigation_failures` (`repeated_mitigation_failure` + dismissed dependency mitigations)
- `most_affected_projects` / `most_affected_departments`
- `risk_heatmap` cells: `{ vertical, risk_level, project_count, avg_score }`

Trend points add recommendation create/accept/dismiss and escalation-suggestion created counters.

## Filters

| Param | Values |
|-------|--------|
| `days` | `7`, `30`, `90`, `365` (else → 30) |
| `project_id` | Optional UUID |
| `vertical` | Optional department/vertical string (case-insensitive) |

Cache keys include org/role/user/days/project_id/vertical. Writes still invalidate by org.

## Drill-down

Portfolio ranking / affected project / heatmap department → focus project → AI recommendations panel + project governance sheet.

## Export

CSV/PDF include insights KPIs, ranking, top risks/blockers, departments, heatmap, and recommendations. Same RBAC as analytics reads; audited as `dashboard.exported`.

## Latency notes

- Summary remains one unified metrics execute (+ in-process cache)
- Detail adds one bounded AI-recommendation window query (execute metadata = 3)
- No escalation detection or LLM on dashboard paint

## Tests

`backend/tests/test_governance_insights_phase11.py` covers scoring, rates, filters, heatmap/blockers, trend counters, cache keys, and summary/detail contracts.

## Related

- [Recommendation Effectiveness (Phase 12)](governance-recommendation-effectiveness.md)
- [Controlled Recommendation Optimization (Phase 13)](governance-recommendation-optimization.md)
