# Delivery Performance Agent — Dashboard Enhancement (Phase 15.6)

Phase 15.6 redesigns the Delivery dashboard (`frontend/src/routes/delivery.tsx`) into nine
labeled sections that surface the intelligence built in Phases 15.1–15.5. It is a
frontend-only change: every section renders from payloads the page already loaded
(portfolio, root causes, root-cause trends, confidence history, daily actions, briefing),
so no new backend endpoints or migrations were added.

## Section layout

The page is organised top-to-bottom with `SectionGroupHeading` dividers.

| # | Section | Anchor | Content | Source |
|---|---------|--------|---------|--------|
| 1 | Executive delivery overview | `#overview` | Four portfolio KPI cards plus a traffic-light distribution bar (`PortfolioHealthBar`) | `/delivery/portfolio` |
| 2 | Daily operational briefing | `#briefing` | Phase 15.4 `OperationalBriefingPanel` (deterministic sections + optional AI narrative + knowledge evidence) | `/delivery/projects/{id}/operational-briefing` |
| 3 | Root-cause analysis | `#root-cause` | Phase 15.1 `DeliveryRootCauseSection` (confidence-loss factors + trends) | `/delivery/projects/{id}/root-causes`, `/delivery/root-causes/trends` |
| 4 | PM action planner | `#actions` | Phase 15.3 `TodaysFocusPanel` plus the existing `MitigationRecommendationsPanel` | `/delivery/projects/{id}/daily-actions` |
| 5 | Confidence trends | `#confidence` | Historical confidence line chart (unchanged chart, new section) | `/projects/{id}/delivery-confidence` |
| 6 | Team bottlenecks | `#bottlenecks` | `TeamBottlenecksPanel`: open/acknowledged bottlenecks for the focused project, sorted by severity | `bottlenecks` array in the portfolio dashboard |
| 7 | Operational timeline | `#timeline` | `OperationalTimelinePanel`: merged reverse-chronological feed of risk openings, bottleneck detections, milestone completions/misses, and completed PM actions (20 most recent) | Dashboard payload + daily-action history |
| 8 | Delivery insights | `#insights` | `DeliveryInsightsPanel`: deterministic portfolio signals (red projects, lowest-confidence project, open risk/bottleneck totals, worsening/improving root-cause factors, unscored projects) | Portfolio + root-cause trends |
| 9 | Drill-down analytics | `#analytics` | The ranked Project Performance table with a new per-row **Details** expansion showing traffic light, open risks, active bottlenecks, milestone hit rate, and top risks; **Focus** switches the page's focused project | `/delivery/portfolio` |

## New frontend modules

- `frontend/src/features/delivery/insights.ts` — pure derivation functions:
  `deriveTrafficDistribution`, `deriveActiveBottlenecks`, `buildOperationalTimeline`,
  `deriveDeliveryInsights`, `trafficLightLabel`, `milestoneHitRateFor`. All deterministic;
  no AI, no new requests.
- `frontend/src/features/delivery/DashboardSections.tsx` — presentational components:
  `PortfolioHealthBar`, `TeamBottlenecksPanel`, `OperationalTimelinePanel`,
  `DeliveryInsightsPanel`.

## Data reuse notes

- The timeline reads completed-action history through `useProjectDailyActionsQuery`,
  which shares its React Query key with `TodaysFocusPanel`, so mounting both costs one
  request.
- Bottlenecks and timeline events come from the focused project's dashboard inside the
  portfolio payload; changing the "Project focus" selector re-derives both without a
  fetch.
- Insights combine the full portfolio entry list (never a page slice) with root-cause
  trends, so pagination in the analytics table does not change them.

## Access control

Nothing changed server-side. The client role still sees no root-cause trends, PM
actions, or briefing internals: `useRootCauseTrendsQuery` and
`useProjectDailyActionsQuery` are gated on `role !== "client"`, and the briefing endpoint
already redacts client payloads. Sections backed by gated queries render their empty
states for clients.
