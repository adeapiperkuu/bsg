# Quality Intelligence Agent — v1.0 Gaps (MVP vs Full Spec)

This document lists features from [`docs/AI Agents/quality_intelligence_agent_v1_0.md`](../../docs/AI%20Agents/quality_intelligence_agent_v1_0.md) that are **not** included in the Phase 1 MVP implementation. Each gap notes the spec reference, blocking dependency, and recommended phase.

---

## Use Cases Not Implemented

| Gap | Spec | Blocked By | Phase |
|-----|------|------------|-------|
| UC-03 Reviewer calibration trigger | §5 UC-03 | `reviewer_scorecards` table (per-reviewer accuracy, 50+ item minimum) | Phase 2 |
| UC-04 SOP ambiguity workflow + human authorship | §5 UC-04 | `sop_version_history` table, SOP document store | Phase 2 |
| UC-05 What-if scenario analysis | §5 UC-05 | Historical recovery patterns, Operational Knowledge Agent | Phase 2 |
| UC-06 Client quality narrative generation | §5 UC-06 | Client Interaction Agent integration, HITL approval flow | Phase 1.5 |
| UC-07 Cross-project leadership heatmap | §5 UC-07 | Portfolio aggregation UI, leadership-specific API | Phase 2 |

---

## Inter-Agent Signals Not Implemented

| Signal | Target Agent | Spec | Phase |
|--------|-------------|------|-------|
| `quality_risk` payload on drift/rework breach | Delivery Performance (01) | §9.1 | Phase 1.5 |
| Weekly quality report JSON | Client Interaction (05) | §9.2 | Phase 1.5 |
| `skill_gap` payload on onboarding gap | Workforce (03) | §9.3 | Phase 2 |
| Lesson log write-back | Operational Knowledge (06) | §9.4, §8.5, BR-08 | Phase 2 |
| Auto-escalation after 5 business days | Project Governance (04) | §9.5, BR-06 | Phase 2 |

MVP logs drift events locally (`risk_alerts`, `notifications`) but does not emit cross-agent event bus messages.

---

## Data Inputs Not in Schema

| Data Source | Spec §6.1 | MVP Proxy | Phase |
|-------------|-----------|-----------|-------|
| Gold-set evaluation logs (item-level) | Required | Team-level `quality_snapshots` only | Phase 2 |
| IAA measurement records (per reviewer pair) | Required | Team-level IAA on snapshot | Phase 2 |
| Reviewer scorecards | Required | `annotators.created_at` as onboarding proxy | Phase 2 |
| Rework / correction logs | Required | `rework_rate_pct` on snapshot | Phase 2 |
| Onboarding records | Required | `annotators.created_at` within 14 days | Phase 1.5 |
| SOP version history | Required | Error taxonomy `guideline_ambiguity` share | Phase 2 |
| Gold-set metadata | Required | Not tracked (BR-10) | Phase 2 |
| Throughput / workforce allocation cross-ref | §6.1 | Not used in root-cause | Phase 2 |

---

## Reasoning Hypotheses Not Implemented

| Hypothesis | Spec §7.2 | MVP Status |
|------------|-----------|------------|
| Onboarding gap | #1 | Implemented (annotator proxy) |
| SOP change | #2 | Partial (ambiguity error share + IAA drop) |
| Task complexity spike | #3 | Deferred |
| Gold-set version change | #4 | Deferred |
| Workload / fatigue | #5 | Deferred |
| Systemic SOP ambiguity | #6 | Partial |

---

## Threshold & Configuration Gaps

| Gap | Spec | MVP Status |
|-----|------|------------|
| Per-client / per-project / per-task-type thresholds | §12, §16.3 | Global defaults via `metric_configurations.threshold_config` only |
| Threshold change permissions (DQ-032) | §16.3 | Super Admin via existing metrics API; no per-org overrides |

---

## Infrastructure Gaps

| Gap | Spec | MVP Status |
|-----|------|------------|
| Scheduled nightly drift scan | §5 UC-01 | Drift runs on snapshot POST only |
| Real-time gold-set evaluation | §16.3 open question | Batch/cycle-based assumed |
| RAG over unstructured SOPs / calibration decks | §6.2 | Structured DB evidence only |
| Operational Knowledge Agent retrieval | §9.4 | Not available; responses note absence |
| Full ERR-01–ERR-07 enum enforcement | §7.3 | Free-text `error_category` on entries |
| Load test: 20 concurrent NL sessions | §16.4 | Not run in MVP |
| 90% synthetic drift detection validation | §16.4 | Partial unit tests only |

---

## Business Rules Partially Met

| Rule | MVP Status |
|------|------------|
| BR-01 Drift alert includes root-cause | Met when sample size ≥ 30 |
| BR-02 Evidence-backed conclusions | Met via evidence links + grounded context |
| BR-03 No reviewer IDs to clients | Met via `quality_scoping` filters |
| BR-04 Confidence on every diagnostic | Met on drift + NL queries |
| BR-05 Sample size gate | Met (`evaluated_item_count < 30`) |
| BR-06 5-day auto-escalation | Deferred |
| BR-07 DM approval for client narratives | Deferred (UC-06) |
| BR-08 Lesson log on resolution | Deferred |
| BR-09 No direct SOP modification | Met (recommendations only) |
| BR-10 Gold-set version tracking | Deferred |

---

## Recommended Build Order for Remaining v1.0

1. **Phase 1.5:** Inter-agent signals to Delivery + Client Interaction; onboarding records table; scheduled drift re-scan
2. **Phase 2:** Reviewer scorecards, SOP history, OKA integration, lesson write-back, what-if modeling
3. **Phase 2+:** Governance auto-escalation, leadership heatmap, per-org threshold overrides
