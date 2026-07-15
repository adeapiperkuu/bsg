# Governance Recommendation Optimization (Phase 13)

Controlled optimization framework that improves recommendation quality using historical effectiveness data from Phases 9–12.

All improvements are **reviewable, versioned, explainable, reversible, and auditable**. No automatic governance actions.

Cross-links:

- [Governance Insights](governance-insights-dashboard.md)
- [Recommendation Effectiveness](governance-recommendation-effectiveness.md)
- [AI Recommendations](governance-ai-recommendations.md)
- Agent BRD: `docs/AI Agents/04. Project Governance.md`

## Architecture

```
Lifecycle events ──► Effectiveness metrics (Phase 12)
                              │
                              ▼
                   Learning rule proposals
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Shadow eval     Approval       Strategy versions
              │               │               │
              └───────► Active rules (flag) ◄─┘
                              │
                              ▼
                   Drift detection (warnings only)
                              │
                              ▼
                   Evaluation reports + dashboard
```

Reuse:

- Recommendation models and convert flow (Phase 7)
- Lifecycle event table (Phase 12)
- Learning rules table (Phase 12)
- Effectiveness metrics / exports / permissions patterns
- In-process caching (no Redis)

## Recommendation lifecycle

Acceptance, conversion, and resolution remain **separate events**.

Dedicated APIs:

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/governance/recommendations/{id}/convert` | Convert (reuses Phase 7 converters) |
| POST | `/governance/recommendations/{id}/resolve` | Mark resolved |
| POST | `/governance/recommendations/{id}/reopen` | Reopen after resolve |
| POST | `/governance/recommendations/{id}/cancel-resolution` | Clear resolution |
| POST | `/governance/recommendations/{id}/change-conversion-target` | Retarget conversion |
| GET | `/governance/recommendations/{id}/lifecycle` | Full immutable timeline |

Every lifecycle change writes an immutable row to `governance_recommendation_lifecycle_events` and a governance audit event.

New event types: `resolution_cancelled`, `conversion_target_changed`.

Create / dismiss / convert paths also emit lifecycle events.

## Learning rule application engine

Feature flag: `GOVERNANCE_RECOMMENDATION_LEARNING_RULES_ENABLED` (default **false**).

Allowed effects only:

- ranking
- confidence_adjustment (ranking/display only — never overwrites stored `confidence`)
- duplicate_suppression
- cooldown
- explanation_strategy
- evidence_requirements

Never automatically:

- create escalations / actions
- accept or dismiss recommendations
- suppress critical trigger types
- change governance data

Flow:

1. Draft / pending approval
2. Leadership **approve**
3. **Shadow evaluation** (required before activate)
4. Activate (only if flag enabled)
5. Rollback or disable (history retained)

APIs:

- `POST /governance/recommendations/learning-rules/{id}/approve`
- `POST /governance/recommendations/learning-rules/{id}/shadow`
- `POST /governance/recommendations/learning-rules/{id}/rollback`
- `GET /governance/recommendations/learning-rules`

## Shadow evaluation

Runs the rule in-memory against a bounded sample.

Compares baseline vs optimized ranking / confidence adjustments / suppression counts.

`production_unaffected: true` is always recorded. Shadow never mutates live recommendation rankings.

Expected impact is shown before activation.

## Strategy versioning

Each recommendation stores:

- `strategy_version`
- `confidence_version`
- `quality_score_version` / `calibration_version`
- `explanation_version`
- `learning_rule_version` (optional)

Registry table: `governance_recommendation_strategy_versions`.

Historical recommendations remain reproducible under the versions stamped at generation.

## Drift detection

Monitors acceptance, false-positive rate, and volume spikes across the recent vs prior half of the filter window.

Warnings only — **no automatic rule changes**.

`GET /governance/recommendations/optimization/drift`

## Strategy comparison

`GET /governance/recommendations/optimization/compare?strategy_a=&strategy_b=&days=`

Compares volume, acceptance, conversion, resolution, quality, false positives, recurrence.

## Scheduled evaluation reports

Periods: weekly, monthly, quarterly.

`POST /governance/recommendations/optimization/reports?period=weekly`  
`GET /governance/recommendations/optimization/reports`  
`GET /governance/recommendations/optimization/reports/{id}/export?format=json|csv|pdf`

Reuses existing PDF/CSV export helpers.

## Optimization dashboard

Executive dashboard section (leadership / super_admin only):

- Active learning rules
- Pending approvals
- Shadow evaluations
- Drift warnings
- Strategy versions + comparison
- Report generation

Client users never see this section.

## Filters (server-side)

`days`, `project_id`, `vertical`, `trigger_type`, `strategy_version`, `learning_rule_id`, `quality_band`, `confidence_band`, `status`, `date_from`, `date_to`

Applied on optimization summary / drift / comparison loaders.

## Permissions

| Capability | Roles |
|------------|-------|
| Lifecycle convert/resolve/reopen | Delivery Manager, Super Admin |
| View lifecycle timeline | DM, Leadership, Super Admin |
| Optimization summary / drift / shadow / compare / reports | Leadership, Super Admin |
| Approve / rollback / activate rules | Leadership, Super Admin |

Clients never receive learning rules, calibration internals, optimization reports, strategy versions, or drift analytics.

## Performance

- No Redis
- Bounded in-process cache for summary
- Summary endpoints load capped recommendation samples
- Drill-downs / report lists paginated with limits
- Indexes on strategy version, shadow org/status, drift org, evaluation reports

## Testing

Backend: `backend/tests/test_governance_recommendation_optimization_phase13.py`

- Allowed vs forbidden rule effects
- Ranking / confidence / duplicate / evidence application
- Metric separation (accept / convert / resolve)
- Optimization role gates

Frontend: `frontend/src/features/governance/recommendationOptimization.phase13.test.ts`

Regression: Phase 12 effectiveness tests remain the metric source of truth.

## Limitations

- Learning-rule application to live generation is still gated by the feature flag; activate requires prior shadow evaluation.
- Shadow evaluation estimates ranking impact; it does not simulate future human acceptance.
- Phase 7 convert still couples acceptance with conversion for UX; lifecycle events keep both distinct for analytics.
- Scheduled reports are generated on demand via API (cron wiring can call the same endpoint).

## Acceptance checklist

- [x] Explicit lifecycle APIs with immutable audit events
- [x] Learning rules require approval; activate needs shadow + flag
- [x] Rollback / disable without deleting history
- [x] Shadow evaluation does not affect production
- [x] Strategy versions stamped and comparable
- [x] Drift detection warnings only
- [x] Scheduled evaluation report generation + export
- [x] Optimization dashboard (leadership-only)
- [x] Server-side filters
- [x] Organization isolation via existing scoping
- [x] No automatic governance actions
