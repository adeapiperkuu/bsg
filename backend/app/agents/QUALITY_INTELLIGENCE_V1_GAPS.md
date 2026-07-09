# Quality Intelligence Agent — Remaining v1.0 Gaps

**Last updated:** 2026-06-26  
**Spec:** [`docs/AI Agents/quality_intelligence_agent_v1_0.md`](../../docs/AI%20Agents/quality_intelligence_agent_v1_0.md)  
**Roadmap:** [`docs/agents/quality_intelligence_roadmap.md`](../../docs/agents/quality_intelligence_roadmap.md)

This document tracks **remaining** gaps after Phase 1.5 (Connected Agent) and Phase 2.0 (Full Reasoning) implementation. Earlier versions of this file were stale — most MVP/1.5/2.0 capabilities are now shipped.

---

## Phase status summary

| Phase | Status | Notes |
|-------|--------|-------|
| **1.0 MVP** | **Complete** | Dashboard, drift-on-ingest, basic RCA, NL queries, alerts |
| **1.5 Connected** | **Complete** | Scheduler, signal consumption, client §8.4 summary in comms, hard taxonomy, frontend polish |
| **2.0 Full Reasoning** | **Complete** | Item-level logs, enriched signals, UC-02/03/04/05, NL maturity, acceptance tests |
| **2.5 Portfolio & Governance** | **Deferred** | Auto-escalation, leadership heatmap, per-org thresholds |

---

## Implemented (do not rebuild)

### Use cases
| UC | Status | Key paths |
|----|--------|-----------|
| UC-01 Drift detection | **Done** | `drift.py`, scheduled `scan_all_projects()` in `main.py` |
| UC-02 NL diagnostics | **Done** | `query_handler.py` — status/diagnostic/action/impact/historical/what_if |
| UC-03 Calibration | **Done** | `calibration.py`, scorecard API |
| UC-04 SOP ambiguity | **Done** | `sop_ambiguity.py`, `sop_workflow.py`, confirm → `quality_sop_links` |
| UC-05 What-if | **Done** | `what_if.py` |
| UC-06 Client narrative | **Done** | `generate_quality_summary()` wired into weekly comms draft |
| UC-07 Leadership portfolio | **Done** | Leadership API + `frontend/src/routes/leadership.tsx` |

### Inter-agent signals
| Signal | Status | Consumer |
|--------|--------|----------|
| `quality_risk` emit + consume | **Done** | `signals.py` → `quality_signal_consumer.py` (Delivery) |
| `skill_gap` emit + consume | **Done** | `signals.py` → `skill_gap_consumer.py` (Workforce) |
| Weekly quality JSON (§8.4) | **Done** | `generate_quality_summary()` + communications route |
| Lesson write-back (BR-08) | **Done** | `oka_client.py`, `lesson_log.py` |
| Governance auto-escalation | **Deferred** | `check_quality_escalations` exists but not scheduled |

### Data inputs
| Table | Status |
|-------|--------|
| `quality_snapshots`, `quality_error_entries` | **Done** |
| `reviewer_scorecards` | **Done** |
| `gold_set_evaluation_logs` | **Done** — ingest API + RCA reviewer attribution |
| `rework_logs` | **Done** — ingest API + `rework_metrics.py` in signal payload |
| `iaa_measurement_records` | **Done** |
| `onboarding_records` | **Done** |
| `sop_version_history`, `sop_documents` | **Done** |
| `gold_set_metadata` | **Done** |
| `inter_agent_signals` | **Done** — PENDING → CONSUMED/FAILED lifecycle |
| `quality_sop_links` | **Done** — UC-04 audit trail |

### Root-cause hypotheses (§7.2)
All six hypotheses implemented in `root_cause.py`:
onboarding/scorecards, SOP change, gold-set version, workload/fatigue, systemic IAA, SOP ambiguity (+ eval-log reviewer attribution).

### Business rules
| Rule | Status |
|------|--------|
| BR-01 Drift + root-cause | **Met** |
| BR-02 Evidence-backed conclusions | **Met** — citation enforcement in `citations.py` |
| BR-03 No reviewer IDs to clients | **Met** — `quality_scoping.py` + sanitized §8.4 summary |
| BR-04 Confidence on diagnostics | **Met** |
| BR-05 Sample size gate (≥30) | **Met** — dashboard data-gap badge |
| BR-06 5-day auto-escalation | **Deferred** (Phase 2.5) |
| BR-07 DM approval for client narratives | **Met** |
| BR-08 Lesson log on resolution | **Met** |
| BR-09 No direct SOP modification | **Met** — human confirms SOP version link |
| BR-10 Gold-set version tracking | **Met** |

### Infrastructure & testing
| Item | Status |
|------|--------|
| Scheduled nightly drift scan | **Done** — `main.py` lifespan + `dispatch_pending_signals()` |
| ERR-01–ERR-07 hard enforcement | **Done** — `domain.py` validator; `ERR-OTHER` requires `error_note` |
| Synthetic drift ≥90% gate | **Done** — `test_quality_acceptance.py` |
| RBAC persona matrix | **Done** — `test_quality_acceptance.py` |
| 20 concurrent NL sessions | **Done** — lightweight concurrency test |
| Signal consumer integration | **Done** — `test_quality_signal_consumer.py` |

---

## Remaining gaps (Phase 2.5+)

### Governance & portfolio
| Gap | Spec | Phase |
|-----|------|-------|
| Auto-escalation after 5 business days | §9.5, BR-06 | 2.5 |
| Leadership vertical/task-type risk heatmap | UC-07 extension | 2.5 |
| Per-org / per-project / per-task-type threshold overrides + admin UI | §12, §16.3 | 2.5 |

### Reasoning & data (lower priority)
| Gap | Spec | Phase |
|-----|------|-------|
| Task complexity spike hypothesis (#3) | §7.2 | 2.5+ |
| RAG over unstructured SOPs / calibration decks | §6.2 | 2.5+ |
| Real-time gold-set evaluation (vs batch) | §16.3 open question | Product decision |
| PM project-assignment scoping hardening | §14.1 | 2.5 |

### Operational (not code)
- [ ] Apply migrations on staging/prod (`quality_sop_links`, workforce tables, item-level logs)
- [ ] Seed pilot QA export → weekly snapshot + eval/rework log ingestion
- [ ] Configure `LLM_API_KEY`; optionally `LLM_INTENT_ROUTING=true`

---

## Recommended next build order

1. **Phase 2.5:** Wire `check_quality_escalations` to scheduler; emit `quality_escalation` signal to Governance
2. **Phase 2.5:** Leadership heatmap (vertical × task-type risk matrix)
3. **Phase 2.5:** Per-org threshold overrides + audit log
4. **Ongoing:** Pilot data onboarding and DM/QA sign-off
