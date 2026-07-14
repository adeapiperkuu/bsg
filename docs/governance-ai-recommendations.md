# Governance AI Recommendations (Phase 6–9)

Grounded, persisted LLM recommendations for Project Governance, plus deterministic escalation suggestions (Phase 9). Rule-based analytics recommendations remain the deterministic fallback and are unchanged on analytics detail/summary contracts.

## Architecture

```
Governance data
  → rule-based signal candidates
  → evidence bundle (scoped queries only)
  → LLM structured generation (user-triggered)
  → schema + grounding validation
  → duplicate checks
  → persist governance_ai_recommendations
  → dashboard reads persisted rows
  → (Phase 7) convert → action/escalation + conversion row
  → (Phase 8) provenance links on created record
  → (Phase 9) deterministic escalation suggestion scan (explicit only)
```

Analytics detail continues to call `_build_recommendations()` synchronously. It does **not** call the LLM. Escalation suggestion detection does **not** run on dashboard load.

## Rule-based vs AI vs Escalation suggestions

| Source | When | Label |
|--------|------|-------|
| AI | Valid persisted rows after explicit generate | `AI Generated` |
| Rule-based | Always available from analytics detail / generation fallback | `Rule-based` |
| Escalation suggestion | Explicit scan; deterministic triggers | `Escalation Suggested` |

Fallback order for AI cards: persisted AI for current evidence → newly generated valid AI → rule-based → empty state.

## Generation flow

1. `POST /governance/ai-recommendations/generate` (explicit user action)
2. Permission + cooldown + evidence hash reuse checks
3. Evidence assembly + deterministic signals
4. `LLMClient.generate_structured` with prompt `prompts/ai_recommendations.md`
5. Validate schema + grounding
6. Persist + audit

Dashboard first paint never invokes the model. Hover prefetch must not call generate.

## Phase 9 — Escalation suggestions

### Data model

Reuses `governance_ai_recommendations` with:

- `recommendation_type = escalation_required`
- `suggested_actions[].action_type = consider_escalation`
- `auto_detected = true`
- trigger metadata: `trigger_type`, `trigger_entity_type`, `trigger_entity_id`, `trigger_fingerprint`, `severity_score`, `detected_at`
- snooze: status `snoozed` + `snoozed_until` / `snooze_reason`

Migration: `20260713150000_governance_escalation_suggestions_phase9.sql`

### Trigger types (controlled enum)

- `overdue_blocking_dependency`
- `repeated_overdue_dependency` (reserved / future)
- `multiple_blocking_dependencies`
- `critical_delivery_risk`
- `declining_delivery_confidence`
- `unresolved_scope_risk`
- `overdue_critical_action`
- `repeated_mitigation_failure`
- `milestone_at_risk` (reserved)
- `combined_governance_risk` (reserved)

### Deterministic rules (initial)

| Trigger | Condition (thresholds configurable) |
|---------|-------------------------------------|
| Overdue blocking dependency | status=blocking, overdue days ≥ threshold, no covering open escalation |
| Multiple blockers | ≥ N blocking deps on project, ≥1 overdue |
| Critical delivery risk | open/ack high\|critical risk alert within max age, no delivery_risk escalation |
| Declining confidence | ≥ P recent confidence scores, drop ≥ D, current ≤ floor |
| Overdue critical action | open action overdue ≥ days and risk/mitigation keywords |
| Unresolved scope | pending_revision older than threshold |
| Repeated mitigation failure | ≥ N rejected mitigations on project |

Detector never creates escalations. LLM never decides triggers (optional enrichment only).

### Fingerprints & lifecycle

Fingerprint = hash(org, project, trigger_type, entity, evidence bucket, threshold).

| State | Behavior |
|-------|----------|
| active | reused on unchanged fingerprint |
| dismissed | unchanged fingerprint stays suppressed |
| snoozed | suppressed until `snoozed_until`; default policy does not override |
| stale | marked after relevant writes; next scan may supersede/recreate |
| accepted via convert | Phase 7 conversion + Phase 8 provenance |

### API

- `POST /governance/escalation-suggestions/scan`
- `GET /governance/escalation-suggestions`
- `POST /governance/escalation-suggestions/{id}/snooze`
- `POST /governance/ai-recommendations/{id}/snooze` (alias)
- Convert via existing `POST /governance/ai-recommendations/{id}/convert/escalation`
- Dismiss via existing dismiss endpoint

### Feature flags / thresholds

| Setting | Default |
|---------|---------|
| `GOVERNANCE_ESCALATION_SUGGESTIONS_ENABLED` | `false` |
| `GOVERNANCE_ESCALATION_SUGGESTION_OVERDUE_DAYS` | `7` |
| `GOVERNANCE_ESCALATION_SUGGESTION_BLOCKING_COUNT` | `3` |
| `GOVERNANCE_ESCALATION_SUGGESTION_CONFIDENCE_DROP` | `10` |
| `GOVERNANCE_ESCALATION_SUGGESTION_CONFIDENCE_THRESHOLD` | `65` |
| `GOVERNANCE_ESCALATION_SUGGESTION_ACTION_OVERDUE_DAYS` | `5` |
| `GOVERNANCE_ESCALATION_SUGGESTION_COOLDOWN_SECONDS` | `300` |
| `GOVERNANCE_ESCALATION_SUGGESTION_MAX_PER_PROJECT` | `5` |
| `GOVERNANCE_ESCALATION_SUGGESTION_USE_LLM_ENRICHMENT` | `false` |
| `GOVERNANCE_ESCALATION_SUGGESTION_SNOOZE_DAYS` | `7` |

### RBAC / clients

Internal roles only (DM, leadership, super-admin). Clients cannot scan, list, snooze, dismiss, or convert suggestions. No Slack/email in this phase; critical suggestions create in-app governance notifications.

### Performance

- No detection on dashboard first paint
- Analytics summary/detail SQL unchanged
- Explicit scan uses bundled queries (bounded executes, no N+1)
- List endpoints remain lightweight

## Evidence / conversion / provenance

Unchanged from Phases 6–8. Conversion still requires confirmation and never calls the LLM.

## Known limitations

- Some trigger types are reserved for later enrichment.
- Soft mitigation “failure” maps to rejected mitigation recommendations.
- LLM enrichment is optional and off by default.
- Portfolio org-wide scan for super-admin without org context requires a project_id.
- Client-facing escalation summaries are handled separately via
  `POST /governance/escalations/{id}/publish-client-summary` (approval-gated `client_visible`).

## Prior Phase 10 recommendation

Cross-agent combined risk scoring using quality/workforce signals already safely available, deeper milestone-at-risk detection, and optional scheduled background scans — still without auto-creating escalations or loading detection on dashboard paint.
## Phase 10 - Advanced Escalation Detection

Phase 10 completes the reserved escalation trigger set while preserving the review-first model. Suggestions remain `governance_ai_recommendations` rows and escalations are never auto-created.

Migration: `20260713160000_governance_escalation_detection_phase10.sql`

### New Deterministic Triggers

| Trigger | Rule |
|---------|------|
| `repeated_overdue_dependency` | Same overdue blocking dependency is detected across repeated scans using persisted detection history. |
| `milestone_at_risk` | Score over due proximity, unresolved blockers, overdue critical actions, delivery confidence decline, critical delivery risks, dependency severity, and bounded cross-agent signals. |
| `combined_governance_risk` | Requires a configurable number of distinct project risk categories and deduplicates the same underlying evidence. |

Milestone score is capped at 100 and defaults to a threshold of 70. Inputs are deterministic; LLM enrichment, if enabled, can only polish narrative after the trigger has fired.

### Cross-Agent Signals

Optional cross-agent inputs are disabled by default with `GOVERNANCE_ESCALATION_SUGGESTION_CROSS_AGENT_ENABLED=false`.

- Quality: drift alerts, high rework, low accuracy.
- Workforce: critical/high open capability gaps and overloaded utilization snapshots.
- Delivery: throughput deterioration, delivery risk alerts, delivery confidence trends.

Provider failures are logged and recorded on scan history, but do not fail the governance scan. Only compact signal metadata is stored on recommendation snapshots.

### Scan History

`governance_escalation_suggestion_scans` records scan type, status, start/completion timestamps, projects checked, signals evaluated, created/refreshed/skipped/suppressed counts, provider failures, duration, and failure reason.

Internal API:

- `GET /governance/escalation-suggestions/scans`

### Additional Settings

| Setting | Default |
|---------|---------|
| `GOVERNANCE_ESCALATION_SUGGESTION_REPEATED_OVERDUE_COUNT` | `2` |
| `GOVERNANCE_ESCALATION_SUGGESTION_OVERDUE_LOOKBACK_DAYS` | `30` |
| `GOVERNANCE_ESCALATION_SUGGESTION_MILESTONE_RISK_THRESHOLD` | `70` |
| `GOVERNANCE_ESCALATION_SUGGESTION_MILESTONE_DUE_DAYS` | `14` |
| `GOVERNANCE_ESCALATION_SUGGESTION_COMBINED_MIN_CATEGORIES` | `2` |
| `GOVERNANCE_ESCALATION_SUGGESTION_CROSS_AGENT_ENABLED` | `false` |
| `GOVERNANCE_ESCALATION_SUGGESTION_QUALITY_WEIGHT` | `10` |
| `GOVERNANCE_ESCALATION_SUGGESTION_WORKFORCE_WEIGHT` | `10` |
| `GOVERNANCE_ESCALATION_SUGGESTION_DELIVERY_WEIGHT` | `10` |
| `GOVERNANCE_ESCALATION_SUGGESTION_MAX_PROJECTS_PER_SCAN` | `25` |
| `GOVERNANCE_ESCALATION_SUGGESTION_MAX_CREATED_PER_SCAN` | `20` |
| `GOVERNANCE_ESCALATION_SUGGESTION_SCHEDULED_ENABLED` | `false` |

Scheduled scans use the same scan service entrypoint and are disabled by default. No new queue, Redis dependency, or dashboard-first-paint scan is introduced.

## Related

- Phase 11 portfolio insights dashboard: `docs/governance-insights-dashboard.md`
- Phase 12 recommendation effectiveness & learning: `docs/governance-recommendation-effectiveness.md`
- Phase 13 controlled recommendation optimization: `docs/governance-recommendation-optimization.md`
