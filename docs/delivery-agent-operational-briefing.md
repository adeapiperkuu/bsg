# Delivery Performance Agent — AI Daily Operational Briefing

**Status:** Implemented in Phase 15.4  
**Scope:** Grounded morning briefing for PMs. Deterministic sections always; optional AI narrative fail-open. Complements structured summary (Phase 3) and Today's Focus (Phase 15.3).

## Purpose

Answer: *What changed overnight, why did confidence move, and what should the PM do first?*

```text
Dashboard facts
  + root_cause_summary (15.1/15.2)
  + todays_focus PM actions (15.3)
  → analytics/operational_briefing.py (deterministic sections)
  → optional ai/summary_service.py narrative (grounded only)
  → Daily Operational Briefing panel
```

AI never invents causes, scores, milestones, or actions. If the LLM is unavailable, the deterministic narrative is returned.

## Sections

| Section | Source |
|---|---|
| Overnight changes | Throughput deltas, risks/bottlenecks opened in lookback window |
| Confidence movement | Stored confidence history + root-cause drivers |
| New risks | Active risks opened overnight |
| Top priorities | Top root-cause factors, then bottlenecks / risks |
| Milestones due soon | Overdue + warning-window milestones |
| Recommended PM actions | Open `todo` rows from today's PM action plan |

## APIs

| Method | Path | Roles |
|---|---|---|
| GET | `/delivery/projects/{id}/operational-briefing` | DM, leadership, super_admin |
| POST | `/delivery/projects/{id}/operational-briefing/generate` | DM, super_admin |
| GET | `/delivery/dashboard/{id}?with_ai_briefing=true` | Attaches briefing + `daily_summary` (internal only) |

Portfolio remains AI-free (`daily_summary` / `operational_briefing` not generated per project in the portfolio payload).

Query params: `with_ai` (default true on GET/POST generate), `as_of` (GET).

## Frontend

`OperationalBriefingPanel` on `/delivery` (after Root Cause, before Today's Focus):

- Deterministic sections by default (fast load)
- **Refresh with AI** for operators (DM / super_admin)
- Hidden from clients

## Contract notes

- `daily_summary` on the project dashboard is the briefing narrative when attached.
- `structured_summary` remains the authoritative deterministic object (Phase 3).
- Clients do not receive root-cause factor detail or recommended PM actions in the briefing.

## Deferred

- 15.6 Broader dashboard redesign  

Phase 15.5 knowledge evidence: [delivery-agent-knowledge-evidence.md](delivery-agent-knowledge-evidence.md).
- Persisted briefing history table (optional; not required)
