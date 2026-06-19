# Project Summary

> **Status note:** Both source documents are explicitly labeled "concept for internal discussion" / "strategic concept proposal" — this initiative has not been formally approved or scoped as an engineering project yet. Tech stack, the day-one client metrics mechanism, and provisional quality thresholds have since been confirmed by the team (Sections 3, 5, 6). Several decisions still remain open per the source material itself — pilot client, exact MVP/Phase boundary, and formal build-vs-partner sign-off. Treat this document as directional until those are resolved (see Section 8).

## 1. One-paragraph description

The product is the **Operations Tower**: an AI-powered operational intelligence layer that BSG (Borek Solutions Group) adds on top of its existing managed data-labeling / data-operations delivery business (delivery teams in India and Kosovo, clients in Life Sciences, Finance/Insurance, and Logistics). It is for BSG's internal delivery staff and for BSG's clients, who today suffer from fragmented operational data (spreadsheets, QA logs, dashboards, SOP repos), high PM overhead, reactive issue handling, and delayed/inconsistent client reporting — all of which stall clients from moving out of AI pilots into reliable production. The product unifies operational data into a governed single source of truth and uses a set of specialized AI "agents" to predict delivery risk, monitor quality drift, and generate transparent, evidence-backed client reporting. It is explicitly **not** about automating away human annotation or SME review work — AI augments the operational layer around that human work, it does not replace it.

## 2. Target users / personas

| Role | Side | What they're trying to accomplish |
|---|---|---|
| Project Manager (PM) | Internal | Daily prioritization without manually consolidating spreadsheets; know which projects are at risk today |
| Delivery Lead / Delivery Manager (India/Kosovo site lead) | Internal | Portfolio-level delivery governance across all teams; approves AI-drafted client communications; owns the automation backlog |
| Operations Manager | Internal | Balance workforce/throughput across teams |
| QA Lead | Internal | See quality-driven delivery risk before it becomes a client issue |
| Resource Manager | Internal | SME allocation and utilization decisions |
| Program / BSG Leadership (Braunschweig HQ) | Internal | Cross-client, cross-site portfolio view: margin, unit economics, automation ROI, churn early-warning, capacity planning |
| Client Stakeholder / Client Program Manager | External (client) | Know their own project's delivery health and quality without waiting on a PM-driven reporting cycle |
| Client Leadership | External (client) | Executive-level confidence that the program is on track, with auditable evidence (especially in regulated domains) |
| Automation Engineer (2 planned, embedded) | Internal | Converts manually identified repetitive operational work into automated tooling |
| Super Admin | Internal | System-level configuration — including which metrics are surfaced on client-facing summaries/dashboards |

Client-side users must only ever see their own projects — tenant isolation is a hard requirement (see Section 6). The Super Admin role is the only role that can change system-wide configuration (e.g., which metrics clients see); it is distinct from Delivery Manager, who operates within a given client engagement rather than configuring the platform.

## 3. Core features (MVP scope)

MVP = the "Phase‑1 trio" explicitly named in the source material: **Delivery Performance Agent + Quality Intelligence Agent + Client Interaction Agent**, plus the minimum data/UI foundation needed to surface them.

1. PM/Delivery Lead views a live dashboard of active projects, rolling daily throughput, % on-time milestones, and auto-flagged bottlenecks.
2. PM views a throughput forecast-vs-actual chart with a computed schedule-confidence score per project.
3. System proactively alerts a PM/Delivery Lead when a project's delay risk crosses a threshold, showing predicted slippage probability and contributing causes (e.g., absenteeism, rework, review turnaround).
4. PM asks the Delivery agent a natural-language question (e.g., "which projects are at risk?") and receives an evidence-backed answer.
5. System recommends workforce rebalancing between an over-utilized and an under-utilized team on a project.
6. QA Lead/PM views a quality dashboard: gold-set accuracy, inter-annotator agreement, rework rate, and drift alerts, by team and by week.
7. System surfaces a root-cause breakdown of quality errors (e.g., boundary precision, class confusion, guideline ambiguity) with a recommended corrective action (e.g., reviewer calibration, SOP update).
8. Client Interaction agent auto-drafts a weekly/executive client status summary; a human Delivery Manager must review and approve it before it is sent.
9. Client and internal users see a delivery-confidence score for the current milestone.
10. Client user asks the system a question about their own project status and gets an answer without waiting on a PM.
11. Client user logs into a role-scoped "Operations Tower" web view showing only their own projects, fully isolated from other clients' data.
12. Delivery Manager logs into a role-scoped view showing all their teams across the Phase‑1 agents and can approve AI-drafted client communications from it.
13. Every AI-generated insight or client-facing narrative links back to the specific source data it was derived from (audit/evidence trail) — no insight may be presented without a citable basis.
14. RBAC restricts what each logged-in role (Client, Delivery Manager) can see and do, based on permissions.
15. Super Admin configures, system-wide, which set of metrics is surfaced on client-facing summaries/dashboards (e.g., the "day-one" metric set) — this is not a hardcoded list, it's an admin-managed setting.

## 4. Explicitly out of scope

- **Automating human annotation/SME review work itself.** The product is an operational intelligence layer *around* delivery, not a replacement for human labelers, scientific reviewers, or SMEs.
- **Workforce & Capability Agent** (Agent 3) — skill-to-project matching, SME coverage, utilization recommendations. Roadmap places this in Phase 2.
- **Project Governance Agent** (Agent 4) — charter generation, scope/dependency tracking, escalation summaries. Phase 2.
- **Operational Knowledge Agent** (Agent 6) — SOP retrieval, historical lessons-learned search. Phase 2.
- **Full Regulatory-Grade Quality Layer** as a standalone cross-cutting system (scorecards, dataset versioning, post-deployment monitoring across all agents) — roadmap places this in Phase 2, bundled with Agents 3/4/6. (Note: some of its metrics, e.g. gold-set accuracy and IAA, already appear on the Phase‑1 Quality Intelligence dashboard — see open question in Section 8.)
- **Automation engineer tooling/pipeline as a shipped product feature** (e.g., "Live automations in production" counts, automation backlog management) — not tagged as Phase 1 in the source.
- **Team Health Score / weekly voice check-ins ("Borek Operational Excellence Agent")** — explicitly feeds the Workforce & Governance agents, both Phase 2+.
- **BSG Leadership's cross-client portfolio analytics** (margin, unit economics, automation ROI across accounts, churn early-warning) — depends on data from Phase 2+ agents/automation tracking; not part of the Phase‑1 trio.
- **Vertical-specific service-pillar workflows** (e.g., Medical AI Model Evaluation, Financial Crime & Risk Signal Validation, Logistics exception coding) — roadmap Phase 3 ("Verticalize").
- **Predictive/advisory forecasting beyond basic throughput forecast and risk scoring** ("the tower advises, not just reports") — roadmap Phase 4.
- **Autonomous multi-agent orchestration and a self-improving recommendation engine** — explicitly listed as "Future" in the Delivery Performance Agent BRD, not current scope.
- **Multi-client/portfolio intelligence, AI relationship sentiment analysis, predictive client-escalation detection** — explicitly listed as "Future" in the Client Interaction Agent BRD.
- **Connecting to real/live client production data before governance sign-off.** Build and test must use synthetic or sanitized operational datasets only; production deployment requires explicit client approval, governance sign-off, security validation, and compliance review.
- **Committing to a build-in-house vs. third-party-partner decision** for the analytics/agent layer (a named example partner appears in the source as an open option, not a decision) — do not assume either path.

## 5. Success criteria

- Agents 1 (Delivery Performance), 2 (Quality Intelligence), and 5 (Client Interaction) are live and instrumented against at least one pilot client's real delivery, quality, and reporting data sources by the end of the Phase‑1 window (~weeks 1–12, per the source roadmap — explicitly called "illustrative," not a committed date).
- Every AI-generated insight or client narrative is traceable to the specific operational evidence it was derived from; no insight ships without a citable source ("Evidence-Backed AI" principle; Client Interaction Agent governance requires "no hallucinated project status").
- A client user account can never retrieve another client's project data (tenant isolation is testable/verifiable, not just stated).
- 100% of AI-drafted outbound client communications are reviewed and explicitly approved by a human Delivery Manager before sending.
- The build/test environment uses only synthetic or sanitized datasets — verifiable absence of live client production data prior to governance/security sign-off.
- A PM/Delivery Lead can submit a natural-language operational query and receive an answer grounded in the underlying delivery data (functional test of the NL query interface).
- **DRAFT quality/SLA thresholds (placeholder, explicitly expected to change — confirmed WIP by the team):**
  - On-time milestone delivery ≥ 90%
  - Schedule confidence (per milestone) ≥ 80% to be flagged "on track"
  - Gold-set accuracy ≥ 95%
  - Inter-annotator agreement (Krippendorff's α) ≥ 0.85
  - Rework rate ≤ 5%
  These are intentionally simple starting values pending refinement by the BSG team; do not treat them as final acceptance criteria — confirm before using them in any contractual or QA-gating context.
- The system supports an admin-configurable set of client-facing metrics rather than a fixed list — Super Admin can add/remove/change which metrics appear on the client-facing summary at any time, without a code change. (Resolves the previous "5 metrics on day one" question: the actual content of that list is a runtime configuration decision, not a build-time requirement.)

## 6. Key constraints

- **Roadmap (illustrative, per source):** Phase 1 — Delivery + Quality + Client Interaction agents, source instrumentation, ~weeks 1–12. Phase 2 — add Workforce, Governance, Knowledge agents + Regulatory-Grade Quality Layer + embed automation engineers, ~months 3–6. Phase 3 — verticalize service pillars, add model-evaluation/AI-agent-assurance lines, ~months 6–9. Phase 4 — predictive/advisory capability, ~months 9+. The source explicitly states actual scope depends on existing tooling and the chosen pilot client.
- **Delivery geography:** BSG delivery operations run from India and Kosovo; clients are based in Europe/USA.
- **Data residency/compliance:** the data fabric layer must be "EU & client-region compliant" with full tenant isolation between clients.
- **Regulated domains:** source data spans Life Sciences/medical AI, Finance/Insurance (KYC/AML, claims, regulated communications), and Logistics — all named as needing auditable, governed handling.
- **Governance is foundational, not optional:** RBAC, permission-aware AI responses, audit logging, human-in-the-loop validation, governance approval workflows, and data lineage tracking are all required, per the source's explicit framing.
- **Data handling during build:** synthetic/sanitized datasets only until client approvals, governance sign-off, security validation, and compliance review are complete.
- **Pilot client/vertical:** not yet selected — explicitly an open decision.
- **Build vs. partner:** the source material left this open, but the team's commitment to its own stack (below) implies an in-house build for the analytics/agent layer rather than partnering on it. Not explicitly confirmed — flag for sign-off rather than treating as fully settled.
- **Tech stack (confirmed by the development team):** React for frontend; Python (FastAPI) for backend/API; PostgreSQL via Supabase for the database. Hosting/cloud provider beyond Supabase, specific LLM vendor, engineering budget, and team size are still not specified.
- **Authentication, RBAC, and tenant isolation (confirmed by the development team):** The platform will use Supabase's built-in authentication system (Supabase Auth) together with PostgreSQL Row-Level Security (RLS) for role-based access control (RBAC) and tenant isolation. No separate identity provider is currently planned. Supabase Auth will manage user authentication, while RLS policies will ensure users can only access data belonging to their authorized organization or role.

## 7. Domain glossary

- **BSG / Borek Solutions Group** — the company building this product; a managed data-labeling/data-operations provider (India, Kosovo delivery) for Life Sciences, Finance/Insurance, and Logistics clients.
- **Operations Tower** — the role-scoped web cockpit (this product's primary UI) that surfaces agent outputs to Client, Delivery Manager, and BSG Leadership users.
- **Agent** (in this context) — a specialized AI capability/feature area within the single unified platform (e.g., "Delivery Performance Agent"), not a separate freestanding bot.
- **Phase‑1 trio** — the three agents (Delivery Performance, Quality Intelligence, Client Interaction) designated as MVP scope.
- **Gold set** — an expert-validated, trusted ground-truth dataset used to measure annotator/reviewer accuracy.
- **IAA (Inter-Annotator Agreement)** — a statistical measure (e.g., Krippendorff's α) of how consistently different reviewers label the same data; used as a quality signal.
- **SME** — Subject Matter Expert; a domain specialist (e.g., radiologist) who reviews/labels data requiring expert judgment.
- **SOP** — Standard Operating Procedure; a documented process reviewers follow, retrievable via the (Phase 2) Operational Knowledge Agent.
- **Quality drift** — a gradual decline in label/output quality over time, detected via trend monitoring.
- **"RAG" — ambiguous, two unrelated meanings appear in the source; do not conflate them:**
  1. *Red/Amber/Green* — a governance status used in the (Phase 2) Project Governance Agent's escalation register.
  2. *Retrieval-Augmented Generation* — the AI architecture pattern named in the Delivery Performance Agent's technical architecture as a way to ground agent outputs in source data.
  Confirm which sense is meant wherever "RAG" appears in future specs.
- **RBAC** — Role-Based Access Control; restricts data visibility/actions by role (Client / Delivery Manager / BSG Leadership) and enforces tenant isolation between clients.
- **Tenant isolation** — the guarantee that one client can never see another client's data.
- **Throughput** — units of labeled/processed data completed per time period (e.g., units/day).
- **Rework rate** — percentage of completed work that must be redone due to quality issues.
- **Schedule confidence** — a computed percentage score indicating likelihood a milestone is hit on time.
- **Escalation** — a flagged issue raised for leadership/client attention requiring action.
- **Scorecard** — a per-annotator/team/project quality rating; part of the Regulatory-Grade Quality Layer.
- **Dataset versioning** — tracking reproducible historical states of a dataset.
- **Post-deployment monitoring** — watching a *client's* AI model/data quality after their model goes live — distinct from monitoring this software product itself.
- **Go-live (client context)** — the point a client's own AI model enters production; the Client Interaction Agent assesses "readiness" for this event. Do not confuse with this project's own release.
- **Automation engineer** — an embedded role (2 planned) converting manual operational work into automated tooling; team placement is undecided.
- **Super Admin** — the system-level role that controls platform-wide configuration, including which metrics are surfaced on client-facing dashboards/summaries. Distinct from Delivery Manager, who works within a client engagement rather than configuring the platform itself.
- **CSAT** — Customer Satisfaction score, collected from clients.
- **KPI semantic layer** — a standardized mapping from raw operational data to consistent, unified business metric definitions; part of the platform's data foundation.

## 8. Open questions

1. Does the full Regulatory-Grade Quality Layer (gold sets, calibration, IAA, audit trails, scorecards, dataset versioning, error taxonomy, post-deployment monitoring) ship as part of Phase‑1 MVP — since the Phase‑1 Quality Intelligence dashboard already shows gold-set accuracy and IAA — or only in Phase 2 as the roadmap states? The two source documents are inconsistent on this point.
2. Which client and which vertical (Life Sciences / Finance / Logistics) will be the pilot? Explicitly undecided.
3. Is the Phase‑1 trio (Delivery, Quality, Client Interaction) formally confirmed as MVP, or still open for debate? Explicitly listed as "to decide with the team."
4. Where do the two automation engineers sit organizationally, and which teams do they support? Explicitly undecided.
5. Build vs. partner is implied (in-house, given the confirmed stack) but not explicitly confirmed — needs formal sign-off rather than being inferred.
6. Which service pillars get built first per vertical, once Phase 3 verticalization begins? Explicitly undecided.
7. Does the full three-vantage-point Operations Tower (Client / Delivery Manager / BSG Leadership), including Leadership's cross-client margin/unit-economics/automation-ROI analytics, ship in Phase 1, or only after the Phase 2 agents that feed some of that data are live?
8. Hosting/cloud provider beyond Supabase, specific LLM vendor, engineering budget, and team size are still undefined.
9. Will RBAC/tenant isolation be implemented via Supabase Auth + Postgres Row-Level Security, or a separate identity provider/SSO?

**Resolved since the prior version of this document:**
- *5 day-one client metrics* → Resolved: not a fixed list. Super Admin configures which metrics are client-facing, system-wide. (See Sections 2, 3, 5.)
- *Numeric SLA/quality targets* → Resolved (provisionally): simple draft thresholds defined and marked WIP, owned by the BSG team, expected to change. (See Section 5.)
- *Tech stack* → Resolved: React, Python/FastAPI, PostgreSQL via Supabase, decided by the development team. (See Section 6.)
