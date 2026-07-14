# Governance Recommendation Effectiveness (Phase 12)

Measure recommendation quality, outcomes, and feedback — then use validated historical performance for bounded ranking, confidence calibration, explanations, and duplicate suppression.

Review-first constraints (unchanged):

- Never auto-accept recommendations
- Never auto-create escalations or actions
- Do not automatically suppress critical recommendations
- Do not fine-tune models automatically
- Do not overwrite original `confidence`
- Dashboard reads do not trigger recommendation scans
- No Redis

Distinct from Knowledge Continuous Learning (also historically labeled Phase 11).

## Lifecycle

Events (table `governance_recommendation_lifecycle_events`):

`created` → `accepted` / `dismissed` / `snoozed` → `converted` → `resolved` / `reopened` → `feedback_submitted` / `false_positive_confirmed`

Acceptance, conversion, and resolution are **separate**. Phase 7 convert still sets acceptance when converting; effectiveness metrics treat:

- **accepted** = `accepted_at` set or acceptance_status in accepted set
- **converted** = `converted_action_id` or `converted_escalation_id`
- **resolved** = `resolved_at` set and not reopened

## Metric formulas

| Metric | Formula |
|--------|---------|
| Acceptance rate | accepted / **reviewed** |
| Dismissal rate | dismissed / **reviewed** |
| Conversion rate | converted / **accepted** |
| Resolution rate | resolved / **converted** |
| False-positive rate | (confirmed + likely FP) / **reviewed** |

`reviewed` = accepted ∪ dismissed.

When a denominator is 0, APIs return `value: null` with `null_reason`.

Timing: average/median seconds to review, convert, and resolve.

Recurrence: `recurrence_after_acceptance_count` / `recurrence_after_dismissal_count` on recommendation rows.

## False positives

Statuses: `confirmed_false_positive`, `likely_false_positive`, `not_false_positive`, `insufficient_evidence`.

Dismissal alone is **not** a false positive. Signals include explicit dismiss reason, inaccurate/missing evidence feedback, and confirmed status.

## Quality score (0–100)

Deterministic weighted components (versioned, default `v1`):

evidence quality, confidence calibration, acceptance, conversion, resolution, user feedback, recurrence — minus FP / duplicate / stale penalties.

Bands: Excellent 90–100, Good 75–89, Mixed 60–74, Weak 40–59, Poor 0–39.

Insufficient outcome data → `provisional` / `insufficient` band (not automatically Poor).

## Confidence calibration

Original `confidence` is never overwritten.

Adds calibrated confidence, band, gap, observed success rate, ECE, Brier score when sample ≥ `GOVERNANCE_RECOMMENDATION_CALIBRATION_MIN_SAMPLE` (default 10). Otherwise falls back to original confidence.

Success for calibration requires acceptance + conversion and not likely/confirmed FP.

## Feedback & learning

Structured feedback fields (additive on `governance_ai_recommendation_feedback`):

accurate, useful, actionable, clear, missing_evidence, duplicate, already_handled, rating, comment (+ legacy `helpful`/`reason`).

`POST /governance/recommendations/{id}/feedback` writes structured feedback + lifecycle event.

Learning rules table (`governance_recommendation_learning_rules`) supports versioned, org-scoped, approvable, reversible rules. Application is gated by `GOVERNANCE_RECOMMENDATION_LEARNING_RULES_ENABLED` (default false). No silent rule changes.

## Category detection

Group by trigger type × severity × confidence band × vertical × explanation version.

Minimum sample: `GOVERNANCE_RECOMMENDATION_EFFECTIVENESS_MIN_SAMPLE` (default 5).

“Frequently accepted / successful” requires conversion + resolution + low FP — not acceptance alone.

## APIs (internal roles only)

| Endpoint | Purpose |
|----------|---------|
| `GET .../effectiveness/summary` | Lean KPIs |
| `GET .../effectiveness/trends` | Daily series |
| `GET .../effectiveness/funnel` | Lifecycle funnel |
| `GET .../effectiveness/timing` | Timing medians/averages |
| `GET .../effectiveness/quality` | Quality bands + samples |
| `GET .../effectiveness/calibration` | Calibration snapshot |
| `GET .../effectiveness/false-positives` | FP breakdown |
| `GET .../effectiveness/frequently-dismissed` | Category table |
| `GET .../effectiveness/frequently-accepted` | Category table |
| `GET .../effectiveness/recurrence` | Recurrence rollup |
| `GET .../effectiveness/drilldown` | Paginated rows |
| `GET .../effectiveness/export` | csv \| json \| pdf |
| `POST /governance/recommendations/{id}/feedback` | Structured feedback |
| `GET /governance/recommendations/{id}/lifecycle` | Event trail |

Filters: `days`, `project_id`, `vertical`, `trigger_type`, `severity`, `status`, `confidence_band`, `quality_band`, `false_positive_status`, `recurring_only`.

Frontend persists `days`, `projectId`, `vertical` in `/governance` URL search params.

## Permissions

Reuse `assert_can_view_ai_recommendations` / `AI_RECOMMENDATION_ROLES`. Clients cannot access effectiveness analytics, structured feedback internals, calibration, or learning rules.

## Caching

Bounded in-process cache (~3 minutes), keyed by org/role/user/filters/section. Cleared on feedback writes.

## Migration

`supabase/migrations/20260713170000_governance_recommendation_effectiveness_phase12.sql`

## Tests

`backend/tests/test_governance_recommendation_effectiveness_phase12.py`

## Related

- [Controlled Recommendation Optimization (Phase 13)](governance-recommendation-optimization.md) — lifecycle APIs, learning-rule approval/shadow/rollback, strategy versions, drift, scheduled reports.
- [Governance Insights](governance-insights-dashboard.md)
- [AI Recommendations](governance-ai-recommendations.md)

## Limitations

- Phase 7 convert still couples accept+convert in one UX action; metrics keep them logically separate via fields.
- Resolution rates improve once Phase 13 resolve/reopen APIs are used in workflows.
- Learning-rule application remains gated by `GOVERNANCE_RECOMMENDATION_LEARNING_RULES_ENABLED` (approve/shadow/rollback added in Phase 13).
- Explanation enrichment with historical category performance is versioned (`explanation_version`) but narrative polish is incremental.
