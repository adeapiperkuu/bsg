# Delivery Performance Agent — Deterministic Structured Summary

**Status:** Implemented in Phase 3  
**Scope:** Deterministic `structured_summary` derived from existing delivery dashboard facts. No AI narrative, no resource-allocation summary, and no Phase 5 client allowlist framework.

## Contract

Project and portfolio dashboard responses now include an additive `structured_summary` object. `daily_summary` remains nullable prose and is still forced to `None` by the dashboard route until optional AI wiring is approved.

```json
{
  "status": "green | yellow | red",
  "headline": "Deterministic short status",
  "key_facts": ["Confidence score: …", "Risk score: …", "Throughput trend: …"],
  "risks": ["high: Title"],
  "delivery_changes": ["Throughput change…", "Overdue milestone…"],
  "bottleneck_summary": {
    "active_count": 0,
    "highest_severity": null
  },
  "data_quality": ["missing_throughput_history"],
  "generated_at": "2026-07-20T12:00:00+00:00"
}
```

Wire traffic-light values remain `green | yellow | red`. UI presentation may continue to label `yellow` as Amber.

## Generation rules

`analytics/summary.py` builds the object from already-scored dashboard inputs. Generation is pure and side-effect free: no DB writes, no AI calls, and no per-project portfolio queries.

| Field | Rule |
|---|---|
| `status` | Current traffic light from scoring |
| `headline` | Insufficient-data headline when no throughput history; otherwise on-track / needs-attention / at-risk for green / yellow / red |
| `key_facts` | Fixed order: confidence, risk, throughput trend, latest throughput, daily target (when set), current milestone, active risk count, active bottleneck count, overdue milestone count |
| `risks` | Open/acknowledged risk titles as `{tier}: {title}`, ordered by severity desc then title asc |
| `delivery_changes` | Throughput delta vs prior snapshot, variance vs daily target, overdue milestones, milestones due within the configured warning window, risks/bottlenecks opened on `as_of_date` |
| `bottleneck_summary` | Count of open+acknowledged bottlenecks only; highest severity among those rows (`resolved` excluded) |
| `data_quality` | Stable codes: `missing_throughput_history`, `missing_daily_target`, `stale_throughput_data`, `quality_drift_signal` |
| `generated_at` | UTC timestamp at assembly time (only non-deterministic field) |

Overdue milestones are derived from already-loaded milestone rows (`missed` / `at_risk`, or planned date before `as_of_date` and not completed). No mitigation-recommendation query is added.

## Client visibility

`structured_summary` is limited to approved aggregate facts. It does **not** include team IDs, headcount, detector evidence, source keys, acknowledgement/resolution audit fields, or risk contributing-cause payloads. Full Phase 5 allowlist shaping of every Delivery surface remains deferred; this Phase only keeps the new summary object client-safe by construction.

Dashboard bottleneck list rows now include additive `severity` for internal operational use. Detector `source_key` / `evidence_json` remain out of the dashboard payload.

## Query and cache behavior

Structured summary is calculated inside the existing `build_dashboard_response` path used by both project dashboard and portfolio aggregation. Portfolio continues to use the single bundled delivery-inputs query and in-process portfolio cache. No per-project query is introduced inside the portfolio scoring loop.

Because the summary is part of the cached portfolio payload, existing `clear_delivery_portfolio_cache(org_id=…)` invalidation after throughput writes, scoring-threshold changes, milestone/risk updates, and bottleneck lifecycle changes also refreshes `structured_summary`.

## Compatibility

- Existing clients that ignore unknown fields continue to work.
- Response schemas accept payloads without `structured_summary` (`None`).
- `daily_summary` remains nullable and unchanged.
- Phase 2 bottleneck detection rules are untouched.

## Deferred

- Optional AI `daily_summary` wiring behind a feature control
- Resource-allocation / staffing summary
- Full Phase 5 client allowlist shaping
- Inter-agent signal refactor
