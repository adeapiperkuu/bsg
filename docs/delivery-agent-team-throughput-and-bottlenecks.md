# Delivery Performance Agent — Team Throughput and Bottlenecks

**Status:** Implemented in Phase 2  
**Scope:** Deterministic internal operational data and lifecycle management. No AI, staffing automation, or client-safe shaping is included.

## Team-throughput contract

`team_throughput_snapshots` is separate from the existing project-level `throughput_snapshots` table. A row records daily, non-cumulative `units_completed` attributed to one team for one project. Its idempotency key is:

```text
(org_id, project_id, team_id, snapshot_date)
```

The table contains tenant/project/team keys, logical reporting date, non-negative completed units, optional non-negative active headcount, controlled source type (`manual`, `import`, `event`, `derived`, `correction`), bounded source reference/notes, actor keys, and timestamps. Composite foreign keys enforce that the project and team belong to the stated organisation and that the team belongs to the stated project.

An explicit `units_completed = 0` is a reported zero-output day. A missing row is unknown data, never zero. There is no organisation timezone field today, so API validation and detection use UTC as the documented fallback reporting boundary.

## Access, ingestion, and correction

Raw team-throughput and bottleneck endpoints are internal only:

- Read: delivery manager, BSG leadership, super admin.
- Create, correct, acknowledge, resolve, and run detection: delivery manager or super admin.
- Client: denied. Clients continue to receive only the existing high-level dashboard/traffic-light contract.

The ingestion service verifies visible project access, active team/project/organisation consistency, and locks the logical snapshot key transactionally across workers. An exact repeat is a no-op: it creates no audit event, detection run, or scoring pass. A changed repeat updates the same row as `correction`, records bounded before/after audit metadata, then runs one detection/scoring sequence. Future UTC reporting dates are rejected.

After the route commits a changed snapshot or bottleneck lifecycle change, only the affected organisation's Delivery portfolio cache is cleared. Scoring-threshold cache entries are not cleared by operational writes.

## Detection formula and safeguards

For a complete valid date, the project denominator is the sum of all active teams' submitted units:

```text
share(team, date) = team_units / total_valid_team_units × 100
historical_share = simple average of valid pre-window daily shares
decline_pct = max(0, (historical_share - current_share) / historical_share × 100)
headcount_change_pct = (current_headcount - historical_headcount) / historical_headcount × 100
```

The current window is the last `observation_days` valid dates. A signal requires every date in that window to have `decline_pct >= decline_threshold_pct`; equality qualifies. The historical baseline excludes the current window and requires at least `minimum_history_days` valid dates. If headcount is required (the default), every relevant observation must have it. A share decline is treated as explained when the proportional headcount decline plus `headcount_tolerance_pct` is at least the share decline.

Default `delivery_bottleneck` configuration:

```json
{
  "observation_days": 5,
  "decline_threshold_pct": 20,
  "recovery_days": 3,
  "historical_window_days": 14,
  "minimum_history_days": 5,
  "minimum_project_units": 1,
  "headcount_tolerance_pct": 5,
  "stale_after_days": 2,
  "maximum_history_days": 90,
  "require_headcount": true,
  "severity_medium_pct": 35,
  "severity_high_pct": 50,
  "severity_critical_pct": 70
}
```

Severity is `low` below `severity_medium_pct`, then `medium`, `high`, and `critical` at each inclusive configured boundary. The detector skips, rather than guesses, when there are no active teams, invalid/future/duplicate observations, incomplete coverage, zero or too-low project output, insufficient history, zero baseline share, missing required headcount, stale input, or a decline explained by headcount.

Valid dates are consecutive observation dates, not necessarily calendar days; this avoids treating non-reporting days as zero. Query history is bounded by `maximum_history_days`.

## Lifecycle and scoring

Detector identity is stable:

```text
delivery-team-throughput-bottleneck:v1:{org_id}:{project_id}:{team_id}
```

The unique source key and a project advisory transaction lock prevent duplicate logical bottlenecks across concurrent detector runs. Lifecycle is:

```text
qualifying signal → open
open → acknowledged
open|acknowledged + N valid recovery days → resolved
open|acknowledged → manually resolved
resolved + new later qualifying evidence → reopen same logical record
```

Acknowledgement records actor/time/note but remains active for scoring. Manual resolution requires a reason and records actor/time. The unchanged evidence fingerprint cannot immediately reopen a manual resolution; a later logical reporting date with new qualifying evidence can reopen the same row and increments its occurrence count. Missing or stale data never counts toward automatic recovery.

Existing Delivery scoring already counts `open` and `acknowledged` bottlenecks: each adds the existing fixed +5 risk contribution, capped at +15, and an active bottleneck makes the traffic light `yellow`. Confidence is unaffected. Resolved bottlenecks are excluded by the existing scoring input query. Wire values remain `green | yellow | red`; the frontend presents `yellow` as Amber.

## Operations, audit, notifications, and rollback

The internal API exposes list/get/create/update team snapshots, list/get bottlenecks, acknowledge, resolve, and manual detection for a project. Lists use bounded limits and offsets; team reads also accept team/date filters, while bottleneck reads accept status/severity/team/created-date filters.

Audit events include snapshot creation/correction and detector create/update/reopen/automatic resolution plus manual acknowledgement/resolution. Audit metadata contains actor, status/severity transition, source key, team ID, and a bounded evidence summary—not the full evidence blob. High/critical new bottlenecks, severity escalation, reopening, and resolution notify internal delivery/leadership recipients. Notification failure is isolated and does not roll back snapshot or bottleneck persistence.

Detection reads a threshold object once (zero DB configuration queries on a valid cache hit), takes one project advisory-lock query, one active-team query, one bounded team-history query, and one detector-bottleneck query. These reads are constant for 1, 25, or 100 teams; writes may scale with changed records.

To roll back operationally, stop calling the new endpoints/detector and restore the prior application release. The additive migration can remain in place without affecting dashboards for projects with no team data. Do not delete historical team snapshots or bottleneck records as part of rollback. A later migration may retire the feature only after an approved data-retention plan.

> Bottleneck detection is deterministic and evidence-based. It does not use AI and does not automatically create escalations or staffing actions.

## Known limitations

- UTC is used until organisation/project timezone ownership is implemented.
- Detection is only as reliable as complete team attribution and headcount reporting.
- There is no bulk import UI or backfill command in Phase 2; approved import/event producers use the same service contract.
- Notifications are internal database notifications, not a durable external delivery/retry system.
