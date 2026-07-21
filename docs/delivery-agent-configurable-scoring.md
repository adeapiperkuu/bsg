# Delivery Performance Agent — Configurable Scoring

**Status:** Implemented in Phase 1  
**Scope:** Organisation-scoped scoring boundaries; scoring weights remain fixed.

## 1. Supported metric keys and payloads

`metric_configurations` contains nullable global templates (`org_id = NULL`) and optional organisation overrides. An active organisation row takes precedence over the global row with the same key. Missing fields in a valid row inherit code defaults. Unknown fields invalidate that whole section.

### `delivery_confidence`

```json
{
  "on_track": 80,
  "critical": 50
}
```

- `confidence >= on_track` is on track.
- `confidence < critical` is red when the corresponding traffic-light rule is enabled.
- Both values are inclusive percentages from 0 through 100 and must satisfy `critical <= on_track`.

### `delivery_risk`

```json
{
  "medium": 30,
  "high": 60,
  "critical": 85,
  "trend_tolerance": 5,
  "throughput_decline_tolerance": 0,
  "milestone_warning_window_days": 14
}
```

- Risk tiers use `>= medium`, `>= high`, and `>= critical`; below `medium` is low.
- `trend_tolerance` is the inclusive flat band used by confidence trend classification. A movement whose absolute percentage is exactly the tolerance is flat.
- `throughput_decline_tolerance` must be exceeded before the existing decline component contributes delivery risk. Its zero default preserves the prior “any positive decline” behavior.
- `milestone_warning_window_days` controls when the existing milestone urgency component begins.
- Risk percentages are 0 through 100 and must satisfy `medium <= high <= critical`. The milestone window is 1 through 365 days.

### `delivery_traffic_light`

```json
{
  "red_on_critical_confidence": true,
  "red_on_critical_risk": true,
  "red_on_critical_open_risk": true,
  "red_on_missed_milestone": true,
  "yellow_on_warning_confidence": true,
  "yellow_on_warning_risk": true,
  "yellow_on_warning_open_risk": true,
  "yellow_on_open_bottleneck": true
}
```

Confidence and risk numeric boundaries have one canonical owner: the confidence and risk sections above. This section only enables or disables the existing combined classification conditions. Red precedence remains ahead of yellow, then green.

Wire values remain `green | yellow | red`; `yellow` is presentation-labeled “Amber” by the frontend.

### `delivery_bottleneck`

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

This immutable, validated section controls the Phase 2 deterministic team-throughput detector. It owns no score weight: existing active bottleneck scoring remains fixed. Day values are bounded; `minimum_history_days <= historical_window_days`, `recovery_days <= observation_days`, the maximum history window covers all required windows, and severity boundaries satisfy `decline <= medium <= high <= critical`. See [Team Throughput and Bottlenecks](delivery-agent-team-throughput-and-bottlenecks.md) for formula and lifecycle details.

## 2. Defaults and compatibility

| Setting | Default | Previous source |
|---|---:|---|
| Confidence on-track | 80 | `ON_TRACK_THRESHOLD` |
| Confidence critical/red-below | 50 | `calculate_status` default |
| Risk medium/warning | 30 | `classify_risk_tier` / `calculate_status` default |
| Risk high | 60 | `classify_risk_tier` default |
| Risk critical/red | 85 | `classify_risk_tier` / `calculate_status` default |
| Trend flat tolerance | 5 | `calculate_trend_direction` default |
| Risk throughput-decline tolerance | 0 | Previous `decline_pct > 0` boundary |
| Milestone warning window | 14 days | `WARNING_WINDOW_DAYS` |
| Bottleneck observation | 5 days | Phase 1 reserved default |
| Bottleneck decline | 20% | Phase 1 reserved default |
| Bottleneck recovery | 3 days | Phase 1 reserved default |
| Bottleneck historical/minimum history | 14 / 5 days | Phase 2 detector default |
| Bottleneck minimum project units | 1 | Phase 2 data-quality guard |
| Headcount tolerance/staleness | 5% / 2 days | Phase 2 detector default |
| Bottleneck severity medium/high/critical | 35% / 50% / 70% | Phase 2 detector bands |

Code defaults remain authoritative fallback values, so an organisation with no database rows produces the exact pre-Phase-1 scores. Percent scores continue to be clamped to `[0, 100]`. Scoring functions do not accept `None`, NaN, or infinity as configuration values; invalid sections fall back.

## 3. Validation and fallback

Each metric row is independently parsed using a frozen Pydantic model with `extra="forbid"`. JSON numbers and booleans must use their native JSON types; numeric strings and string booleans are rejected.

- Missing row: use the complete default section.
- Missing field in an otherwise valid object: merge that field from defaults.
- Non-object JSON, unknown field, invalid type/range, NaN/infinity, or invalid relationship: log `delivery_scoring_thresholds_invalid` and use the complete default section.
- One invalid section does not discard valid sections.
- A configuration-query failure logs `delivery_scoring_thresholds_load_failed` and returns complete defaults; scoring is not failed by configuration availability.

Logs contain organisation, metric key, concise validation location/reason, fallback, source, cache state, and load duration. Full payloads are not logged.

## 4. Loading, caching, and query behavior

`load_delivery_scoring_thresholds()` loads all four keys with one SQL query on a cache miss. Portfolio scoring calls the bulk loader once for all distinct organisations, so a super-admin cross-organisation portfolio also uses one configuration query rather than one query per organisation or project.

Validated models are cached process-locally:

- Key: organisation UUID.
- TTL: 60 seconds.
- Maximum entries: 1,024; the oldest entry is evicted at the bound.
- Concurrency: an async lock prevents cache-miss stampedes.
- Value: frozen `DeliveryScoringThresholds`; sessions and mutable payload dictionaries are never cached.

`invalidate_delivery_scoring_thresholds_cache(org_id)` invalidates one organisation. Passing `None` invalidates all entries. Successful create/update/delete operations on `/metric-configurations` invalidate the threshold cache and the affected Delivery portfolio cache after commit. A global-template edit clears both caches globally.

## 5. Scoring entry points

- Throughput ingestion calls `run_delivery_scoring`, which loads thresholds once before event creation and reuses them for scoring, milestone classification, risk tiers, and traffic light.
- Direct `run_delivery_scoring` calls use the same path.
- Project dashboard calculation loads the project organisation’s thresholds once.
- Portfolio calculation bulk-loads thresholds before its project loop and passes the immutable model into pure CPU scoring.
- Event handlers receive already-computed scores and do not reload configuration.

The existing portfolio data bundle remains one database call. No configuration lookup occurs inside `_score_projects`.

## 6. Threshold audit

| Existing value | Classification | Phase 1 decision |
|---|---|---|
| Confidence on-track `80` | Boundary | Configurable. |
| Confidence critical `50` | Boundary | Configurable. |
| Risk medium `30`, high `60`, critical `85` | Boundaries | Configurable. |
| Trend flat tolerance `5%` | Boundary | Configurable. |
| Milestone warning window `14` days | Boundary | Configurable. |
| Alert confidence/risk change `5` | Notification suppression threshold | Retained fixed; it does not calculate or classify a score. |
| Confidence trend `+5/-10` | Weights | Retained fixed. |
| Confidence shortfall multiplier `1.25`, cap `35` | Weights/cap | Retained fixed. |
| Throughput multiplier `0.75`, cap `25` | Weights/cap | Retained fixed. |
| Overdue `30`, milestone urgency cap `20` | Weights | Retained fixed. |
| Bottleneck `5` each, cap `15` | Weights | Retained fixed; detector deferred. |
| Quality drift base `5`, cap `15`, divisor `2` | Weights | Retained fixed. |
| Score clamp and percent normalization `0/100` | Algorithmic constants | Retained fixed. |
| Rolling window `7`, history count `3` | Algorithmic window | Retained fixed. |
| Recommendation fallback probabilities `.45/.65/.80/.90` | Recommendation metadata | Retained fixed; not scoring bands. |

The client home page uses confidence thresholds only for visual text colour. It does not derive or send a Delivery traffic light. Delivery status and portfolio classifications use the backend-provided `traffic_light` value.

## 7. Operations

### Change thresholds

1. As super admin, create or update an organisation override through `/metric-configurations`; use one of the four exact keys and set `org_id`.
2. The successful commit invalidates affected caches automatically. Direct database edits take effect after the 60-second TTL unless an application invalidation is triggered.
3. Trigger an explicit scoring run only if a new persisted confidence/risk record is required immediately. Dashboard and portfolio calculations apply thresholds on their next uncached read.
4. No process restart or frontend deployment is required.

> Threshold changes affect subsequent uncached scoring operations. They do not automatically rewrite historical score records unless an explicit recalculation is triggered.

### Roll back

Soft-delete the organisation override or restore its prior JSON. After cache invalidation/expiry, the loader falls back to the global template and then code defaults. Historical scores remain unchanged unless explicitly recalculated.
