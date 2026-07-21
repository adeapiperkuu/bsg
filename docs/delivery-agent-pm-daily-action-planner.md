# Delivery Performance Agent — PM Daily Action Planner

**Status:** Implemented in Phase 15.3  
**Scope:** Deterministic ranked daily focus list with optional AI rationale grounded in evidence. Complements `mitigation_recommendations`; does not replace them.

## Purpose

Answer: *What should the PM focus on today?*

```text
Root causes + bottlenecks + pending mitigations + milestone pressure
  → analytics/pm_actions.py (rank, urgency, impact, due dates)
  → delivery_pm_daily_actions
  → Today's Focus panel
```

Optional AI (`ai/pm_action_rationale.py`) may rephrase `deterministic_rationale` only. It never invents ranks, causes, or impact points.

## Database

Migration: `supabase/migrations/20260720150000_delivery_pm_daily_action_planner.sql`

`delivery_pm_daily_actions`:

| Field | Role |
|---|---|
| `plan_date`, `rank` | Day-scoped priority order |
| `title`, `description` | Action copy |
| `deterministic_rationale` | Always present |
| `ai_rationale` | Optional grounded rewrite |
| `urgency` | `low\|medium\|high\|critical` |
| `estimated_impact_points` | Confidence points recoverable if completed |
| `due_date` | Urgency-derived |
| `status` | `todo\|done\|skipped\|deferred` |
| `source_type` / `source_key` | Evidence link |
| `root_cause_factor`, `mitigation_recommendation_id` | Optional links |
| `evidence_json` | Snapshot of ranking inputs |
| `completed_at` / `completed_by` / `completion_note` | History |

Unique open todo per `(project_id, plan_date, source_key)`. RLS: DM ALL, leadership SELECT, super_admin ALL; no client.

## Ranking rules

1. Root-cause factors with impact > 0 → factor-specific actions  
2. Open/acknowledged bottlenecks  
3. Pending mitigation recommendations  
4. Overdue / near-term milestones  

Deduplicate by `source_key`, sort by urgency then score, cap at N (default 8).

Due dates: critical = today, high = +1d, medium = +3d, low = +5d.

## APIs

| Method | Path | Roles |
|---|---|---|
| GET | `/delivery/projects/{id}/daily-actions` | DM, leadership, super_admin |
| POST | `/delivery/projects/{id}/daily-actions/generate` | DM, super_admin |
| POST | `/delivery/daily-actions/{id}/complete` | DM, super_admin |

Generate accepts `with_ai_rationale` (default false) and `limit`.

## Frontend

`TodaysFocusPanel` on `/delivery` (after Root Cause, before Mitigations):

- Ranked todo list with urgency, impact, due date  
- Done / Skip / Defer for operators  
- Recent completion history  
- Refresh / Generate controls  

Clients do not see the panel.

## Hook

After scoring → root-cause refresh → `safe_generate_daily_actions_after_scoring` (failure-isolated).

## Deferred

- 15.6 Broader dashboard redesign  

Phase 15.4 briefing wired to this plan: [delivery-agent-operational-briefing.md](delivery-agent-operational-briefing.md).  
Phase 15.5 knowledge evidence: [delivery-agent-knowledge-evidence.md](delivery-agent-knowledge-evidence.md).
