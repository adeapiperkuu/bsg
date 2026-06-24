# Quality Intelligence Agent — Implementation Guide
**Agent ID:** 02  
**Agent Name:** Quality Intelligence Agent  
**Suite:** BSG AI-Native Operations Suite  
**Phase:** Phase 1 (MVP — build alongside Agent 01 and Agent 05)  
**Document version:** 1.0  
**Status:** Implementation-ready specification  

---

## Table of Contents

1. [Agent Overview](#1-agent-overview)
2. [Mission Statement](#2-mission-statement)
3. [User Personas](#3-user-personas)
4. [User Stories](#4-user-stories)
5. [Functional Use Cases](#5-functional-use-cases)
6. [Data Inputs](#6-data-inputs)
7. [Agent Capabilities & Reasoning Logic](#7-agent-capabilities--reasoning-logic)
8. [Outputs & Response Formats](#8-outputs--response-formats)
9. [Inter-Agent Interactions](#9-inter-agent-interactions)
10. [Conversational Interaction Patterns](#10-conversational-interaction-patterns)
11. [Business Rules](#11-business-rules)
12. [Thresholds & Alert Conditions](#12-thresholds--alert-conditions)
13. [Error Handling & Edge Cases](#13-error-handling--edge-cases)
14. [Governance & Security](#14-governance--security)
15. [Success Metrics](#15-success-metrics)
16. [Implementation Notes](#16-implementation-notes)

---

## 1. Agent Overview

The Quality Intelligence Agent is the quality monitoring and root-cause reasoning component of the BSG AI-Native Operations Suite. Its primary function is to detect annotation quality problems **before they reach the client**, not after, by continuously monitoring gold-set accuracy, inter-annotator agreement, rework rates, and error taxonomy patterns across all active projects.

The agent operates on two modes simultaneously:

- **Passive / Push mode:** Continuously watches incoming quality data and fires alerts automatically when thresholds are breached or trajectories indicate imminent drift. No user action required to trigger this.
- **Active / Pull mode:** Responds to natural language queries from authorized users through the Operations Tower conversational interface.

The agent does not just report metrics. It reasons about them. Every alert must include a root-cause diagnosis, a severity classification, and one or more ranked recommended actions — all traceable to the underlying operational data.

---

## 2. Mission Statement

> *"Continuously monitor annotation quality signals across all active projects, detect drift and error pattern emergence before they impact delivery or reach the client, identify root causes with evidence-backed reasoning, and generate actionable recommendations that feed into reviewer calibration, SOP improvement, and workforce planning."*

---

## 3. User Personas

| Persona | Role | Primary Need | Access Level |
|---|---|---|---|
| Delivery Manager | India / Kosovo site lead | Full quality picture per team and project, early warnings, actionable recommendations | Full — all teams, all metrics, reviewer-level detail |
| QA Lead | Internal quality reviewer | Reviewer-level accuracy, IAA scores, error taxonomy breakdown, calibration triggers | Full — reviewer-level, error-level detail |
| Project Manager | Per-project PM | Quality status for their project(s) only, rework impact on schedule | Scoped — their projects only |
| Operations Manager | Throughput and staffing lead | Rework rates as a delivery risk signal, capacity impact of quality issues | Partial — aggregate quality metrics, rework volume |
| Borek Leadership | Braunschweig HQ | Cross-project, cross-client quality trends, governance risk, regulatory posture | Aggregate — no client-specific data mixed |
| Client Stakeholder | External client program lead | High-level quality confidence, drift events and their resolution status | Restricted — narrative summary only, no reviewer identity, no raw error logs |

---

## 4. User Stories

### 4.1 Delivery Manager Stories

**QIA-US-01**
> As a Delivery Manager, I want to see a real-time quality dashboard for all my teams so that I can spot problems before they affect delivery commitments.

**QIA-US-02**
> As a Delivery Manager, I want to receive automatic drift alerts with root-cause analysis already attached so that I don't have to investigate manually before deciding on a course of action.

**QIA-US-03**
> As a Delivery Manager, I want to ask the agent "what should I focus on today for quality?" and get a prioritized action list so that I can triage my attention efficiently.

**QIA-US-04**
> As a Delivery Manager, I want to see which specific reviewers are driving the most errors so that I can target calibration sessions where they will have the most impact.

**QIA-US-05**
> As a Delivery Manager, I want to understand the delivery schedule impact of a quality issue before I decide on a remediation approach so that I can make a trade-off decision.

### 4.2 QA Lead Stories

**QIA-US-06**
> As a QA Lead, I want to see a breakdown of error categories by week so that I can identify whether specific error types are trending up and intervene before they become systemic.

**QIA-US-07**
> As a QA Lead, I want to see inter-annotator agreement (IAA) scores per reviewer and per task type so that I can identify where guideline interpretation is diverging.

**QIA-US-08**
> As a QA Lead, I want the agent to recommend targeted calibration content when a systematic error pattern is identified so that I can run efficient sessions without starting from scratch.

**QIA-US-09**
> As a QA Lead, I want the agent to flag when a rework rate spike correlates with a new reviewer cohort versus a SOP ambiguity versus a task complexity change so that I can apply the right fix.

**QIA-US-10**
> As a QA Lead, I want quality events and their resolutions to be automatically logged as lessons learned so that future reviewer cohorts benefit without relying on knowledge transfer between individuals.

### 4.3 Project Manager Stories

**QIA-US-11**
> As a Project Manager, I want to see quality KPIs for my project only so that I have the context I need without noise from unrelated projects.

**QIA-US-12**
> As a Project Manager, I want to know when a quality issue will delay a milestone and by how much so that I can update the client proactively rather than reactively.

### 4.4 Client Stories

**QIA-US-13**
> As a Client Stakeholder, I want a plain-language quality summary in my weekly report so that I understand whether my data program is meeting quality standards without needing to interpret raw metrics.

**QIA-US-14**
> As a Client Stakeholder, I want to know when a quality incident occurred and how it was resolved so that I have confidence in the governance process even when things go wrong.

### 4.5 Leadership Stories

**QIA-US-15**
> As Borek Leadership, I want cross-project quality trend data so that I can assess overall delivery quality posture and identify systemic issues that transcend individual projects.

**QIA-US-16**
> As Borek Leadership, I want to know which verticals or task types carry the highest quality risk so that I can prioritize investment in tooling, training, or SME hiring.

---

## 5. Functional Use Cases

### UC-01: Automated Drift Detection and Alert

**Trigger:** Scheduled quality check runs (e.g. nightly, or post gold-set evaluation batch).

**Precondition:** Gold-set evaluation data is available for the current week. Prior-week baseline exists.

**Main flow:**
1. Agent ingests the latest gold-set accuracy scores per team and per project.
2. Agent computes week-over-week delta for each team.
3. Agent evaluates against drift threshold rules (see Section 12).
4. If a threshold breach or adverse trajectory is detected:
   - Agent runs root-cause analysis across QA logs, IAA records, reviewer scorecards, error taxonomy data, and SOP change history.
   - Agent identifies the top contributing factors and their percentage weight.
   - Agent retrieves relevant historical lessons and SOP references from the Operational Knowledge Agent.
   - Agent generates a drift alert with: affected team, metric values, root-cause breakdown, severity tier, and ranked recommended actions.
5. Alert is pushed to the Delivery Manager's dashboard and notification queue.
6. Agent simultaneously notifies the Delivery Performance Agent (throughput risk signal) and the Project Governance Agent (potential at-risk item).

**Postcondition:** Drift alert is visible in the Operations Tower. Downstream agents have been notified. No human action was required to initiate the process.

**Exception flow:** If gold-set data is incomplete (e.g. fewer than the minimum sample size of evaluated items), agent flags data quality gap rather than issuing a false alert. It logs the gap and waits for the next evaluation cycle.

---

### UC-02: Root-Cause Diagnosis on Query

**Trigger:** User types a natural language question into the Operations Tower interface.

**Precondition:** User is authenticated and has access to the relevant project scope.

**Example queries:**
- "Why is Pathology accuracy dropping?"
- "Which error categories are increasing this week?"
- "What's driving rework on the Clinical NLP project?"

**Main flow:**
1. Agent parses the query and identifies the target project/team, time window, and quality dimension.
2. Agent retrieves relevant data slices: error taxonomy breakdown, reviewer scorecard deltas, IAA trends, SOP version history, onboarding records for new reviewers.
3. Agent performs root-cause reasoning. It checks these factors in order:
   - New reviewer cohort onboarded recently? (onboarding gap hypothesis)
   - SOP version change in the relevant period? (guideline change hypothesis)
   - Task complexity spike (new tile type, new data source)? (complexity hypothesis)
   - Seasonal or workload-driven fatigue signal? (workforce hypothesis)
   - Gold-set itself updated recently? (calibration drift hypothesis)
4. Agent quantifies the contribution of each confirmed factor as a percentage.
5. Agent retrieves matching historical lessons and SOP guidance from the Operational Knowledge Agent.
6. Agent returns: root-cause breakdown, confidence level, supporting evidence citations, and recommended actions.

**Response must include:**
- What is happening (the metric, the delta)
- Why it is happening (root-cause breakdown with percentages)
- What to do about it (ranked actions)
- Confidence level in the diagnosis
- Source citations (QA log references, reviewer IDs if authorized, SOP versions, lesson IDs)

**Postcondition:** User has a diagnosis and an action plan. No separate manual investigation required.

---

### UC-03: Reviewer Calibration Trigger

**Trigger:** Root-cause analysis identifies that one or more specific reviewers account for a disproportionate share of errors in a given category.

**Precondition:** Reviewer scorecard data is available. Minimum sample size (e.g. 50+ evaluated items per reviewer) is met to ensure statistical validity.

**Main flow:**
1. Agent identifies which reviewers are above-threshold error contributors for a specific error category and task type.
2. Agent determines whether the error pattern is isolated to those reviewers (training gap) or shared across the team (SOP gap).
3. If reviewer-specific:
   - Agent generates a calibration recommendation specifying: reviewer IDs, error category, task type, suggested calibration content (worked examples, SOP sections, historical lesson references).
   - Agent sends recommendation to QA Lead via Operations Tower notification.
4. If team-wide:
   - Agent escalates to SOP ambiguity flag and recommends a SOP update (see UC-04).
5. Agent flags affected output batches as pending re-review until calibration is confirmed complete.

**Postcondition:** QA Lead receives a targeted calibration brief. Affected output is held from delivery queue. Workforce Agent is notified of the calibration event for capacity planning.

---

### UC-04: SOP Ambiguity Detection and Update Trigger

**Trigger:** IAA scores drop significantly across multiple reviewers on the same task type, without a corresponding new-reviewer onboarding event.

**Precondition:** IAA data is available for the current week. At least 3 reviewers are evaluated on the same task type.

**Main flow:**
1. Agent detects IAA drop that is distributed across reviewers (not concentrated on new cohort members).
2. Agent checks SOP version history for the relevant task type. If a recent SOP change correlates with the IAA drop, it confirms the hypothesis.
3. Agent generates a SOP ambiguity flag specifying: task type, the specific annotation decision where reviewers are diverging (based on error taxonomy pattern), confidence in the diagnosis, and recommended SOP clarification with example.
4. Agent sends flag to QA Lead for human review and SOP update authorship.
5. Upon SOP update confirmation, agent logs the event and links the updated SOP version to the triggering quality event in the audit trail.

**Postcondition:** SOP ambiguity is identified and routed for resolution. Audit trail records the quality-event-to-SOP-update chain.

---

### UC-05: What-If Scenario Analysis

**Trigger:** User explicitly asks the agent to model the quality risk of a proposed decision or alternative approach.

**Example queries:**
- "If we skip calibration and just re-review the affected tiles, what's the quality risk next week?"
- "What happens to rework rate if we reassign 10 annotators from Radiology to Pathology?"
- "How long will it take for accuracy to recover if we run calibration on Tuesday?"

**Main flow:**
1. Agent identifies the decision variable and the outcome metric of interest.
2. Agent retrieves current error rates, reviewer performance distributions, and historical recovery patterns from similar past events (via Operational Knowledge Agent).
3. Agent models the likely outcome under the proposed scenario, stating assumptions explicitly.
4. Agent returns: projected outcome, confidence range, key assumptions, comparison to the recommended approach if different.

**Postcondition:** User has a modeled projection to inform their decision. The agent does not make the decision — it surfaces the evidence.

---

### UC-06: Client Quality Narrative Generation

**Trigger:** Weekly executive summary generation cycle (automated, triggered by Client Interaction Agent).

**Precondition:** Weekly quality data is finalized and validated.

**Main flow:**
1. Client Interaction Agent requests a quality summary from the Quality Intelligence Agent.
2. Quality Intelligence Agent generates a client-facing quality narrative containing:
   - Overall quality status (on track / at risk / critical)
   - Gold-set accuracy figure (blended)
   - Rework rate vs target
   - Any drift events that occurred during the period and their resolution status
   - A single plain-language sentence summarizing the quality posture
3. The narrative must NOT include: reviewer names or IDs, raw error log references, internal SOP identifiers, or any detail that would reveal internal process complexity.
4. Narrative is returned to the Client Interaction Agent for inclusion in the executive summary.
5. Delivery Manager reviews and approves before the summary is sent to the client.

**Postcondition:** Client receives a quality update that is accurate, non-technical, and reflects real underlying data — with no risk of exposing internal operational detail.

---

### UC-07: Cross-Project Quality Trend Reporting (Leadership)

**Trigger:** Leadership requests a portfolio-level quality overview, or scheduled weekly leadership report generation.

**Main flow:**
1. Agent aggregates gold-set accuracy, IAA, and rework rate across all active projects.
2. Agent identifies which verticals, task types, or teams carry the highest error concentration.
3. Agent surfaces systemic patterns — e.g. "Model-eval tasks consistently score lower than segmentation tasks across three projects — possible training investment gap."
4. Agent generates a cross-project quality heatmap and a brief narrative summary for leadership.

**Postcondition:** Leadership has a portfolio quality view that supports strategic decisions about hiring, training, and tooling investment.

---

## 6. Data Inputs

### 6.1 Structured Sources

| Data Source | Fields Required | Update Frequency |
|---|---|---|
| Gold-set evaluation logs | project_id, team_id, reviewer_id, task_type, item_id, score, error_category, evaluation_date | Per evaluation batch |
| IAA measurement records | project_id, task_type, reviewer_ids_compared, agreement_score (Krippendorff α), measurement_date | Per evaluation cycle |
| Reviewer scorecards | reviewer_id, project_id, task_type, accuracy_score, error_breakdown, week | Weekly |
| Rework / correction logs | project_id, team_id, item_id, rework_reason, rework_date, reviewer_id_original, reviewer_id_corrector | Daily |
| Onboarding records | reviewer_id, project_id, task_type, onboarding_date, calibration_status | On event |
| SOP version history | sop_id, version, effective_date, task_type, change_summary | On update |
| Error taxonomy reference | error_category_id, error_category_name, description, severity_weight | Static with periodic updates |
| Gold-set metadata | gold_set_id, project_id, task_type, version, item_count, last_updated | On update |
| Throughput logs (from Agent 01) | project_id, team_id, units_per_day, date | Daily |
| Workforce allocation (from Agent 03) | reviewer_id, project_id, allocation_pct, skill_level, date | Weekly |

### 6.2 Unstructured Sources (via RAG)

- SOP documents (full text, versioned)
- Calibration decks and worked examples
- Historical lessons learned (from Operational Knowledge Agent index)
- Project charters (for task type and domain context)
- Escalation notes from prior quality events

### 6.3 Minimum Data Requirements

The agent must not generate root-cause conclusions or drift alerts unless the following minimums are met:

- Gold-set evaluation: minimum **30 evaluated items** per team per week.
- IAA measurement: minimum **3 reviewers** evaluated on the same task type.
- Reviewer scorecard: minimum **50 evaluated items** per reviewer before reviewer-level conclusions are drawn.

If minimums are not met, the agent must state: "Insufficient sample size for conclusive analysis. [X] items evaluated; minimum is [Y]. Data gap flagged."

---

## 7. Agent Capabilities & Reasoning Logic

### 7.1 Quality Drift Detection

The agent computes week-over-week and rolling-trend delta for:
- Gold-set accuracy per team (blended and per task type)
- Rework rate per project
- IAA per task type

**Drift detection logic:**

```
IF (current_week_accuracy < prior_week_accuracy - DRIFT_THRESHOLD)
  OR (current_week_accuracy < FLOOR_THRESHOLD)
  OR (rolling_3week_trend is declining AND slope > TREND_THRESHOLD)
THEN → trigger drift alert
```

See Section 12 for threshold values.

### 7.2 Root-Cause Reasoning

When a drift or rework spike is detected, the agent runs a structured hypothesis evaluation in this order:

1. **Onboarding gap hypothesis**: Were new reviewers added to this team in the past 2 weeks? Cross-reference onboarding records. If yes, isolate error contribution of new vs. tenured reviewers. If new reviewers account for >50% of errors, this is the primary root cause.

2. **SOP change hypothesis**: Was the SOP for this task type updated in the past 3 weeks? If yes, check whether the error spike is distributed across reviewers (SOP change is more likely to cause team-wide errors than individual ones). Correlate SOP change date with accuracy timeline.

3. **Task complexity hypothesis**: Was a new tile set, data source, or annotation guideline introduced? Check project charter and task log for new cohort introductions. Complexity spikes cause temporary accuracy dips even for experienced reviewers.

4. **Gold-set version hypothesis**: Was the gold-set itself updated? A harder or differently calibrated gold set can cause apparent accuracy drops that don't reflect actual reviewer performance degradation.

5. **Workload / fatigue hypothesis**: Is the team at or above 100% utilization? Cross-reference workforce allocation data. High utilization sustained for >2 weeks correlates with gradual accuracy decline.

6. **Systemic SOP ambiguity hypothesis**: If IAA is low and the error pattern is evenly distributed across reviewers (not concentrated on new cohort or single individuals), the SOP guidance itself may be ambiguous. Flag for SOP review.

**Output format for root cause:**

```
Root cause breakdown:
- [Factor 1]: [X]% contribution — [evidence citation]
- [Factor 2]: [Y]% contribution — [evidence citation]
- [Factor 3]: [Z]% contribution — [evidence citation]
Primary driver: [Factor 1]
Confidence: [High / Medium / Low]
```

Confidence levels:
- **High**: Primary factor accounts for >50% of errors, evidence is direct (e.g. error log + onboarding date correlation).
- **Medium**: Primary factor is plausible but competing hypotheses cannot be fully ruled out.
- **Low**: Multiple factors at similar weight, insufficient data to isolate primary cause. State this explicitly.

### 7.3 Error Taxonomy Classification

Every quality event must be classified against the standard error taxonomy. The minimum required categories are:

| Category ID | Category Name | Description |
|---|---|---|
| ERR-01 | Boundary precision | Inaccurate placement of annotation boundaries |
| ERR-02 | Class confusion | Item annotated with the wrong class label |
| ERR-03 | Missed object | Annotatable item not labeled |
| ERR-04 | Guideline ambiguity | Annotation inconsistent with SOP but SOP is unclear |
| ERR-05 | False positive | Non-annotatable item incorrectly labeled |
| ERR-06 | Attribute error | Correct class but wrong attribute (e.g. severity, orientation) |
| ERR-07 | Tool error | Correct intent but annotation tool used incorrectly |
| ERR-OTHER | Other | Errors not fitting above categories (must include free-text note) |

The taxonomy is extensible. New categories can be added by QA Lead with agent awareness updated accordingly.

### 7.4 Recommendation Generation

For every root cause identified, the agent must generate at least one recommended action. Actions are ranked by expected impact on quality recovery speed.

**Recommendation structure:**

```
Recommended action [rank]:
- Action: [What to do]
- Target: [Who should do it / what is affected]
- Expected outcome: [What metric should improve and by how much]
- Estimated effort: [Time / resource cost]
- Evidence basis: [Lesson ID, SOP reference, or historical pattern]
- Priority: [Immediate / This week / Next sprint]
```

### 7.5 Confidence Scoring

Every agent response must include a confidence score. This is not optional — it is a core design principle.

| Level | Meaning | When to use |
|---|---|---|
| High (>80%) | Strong evidence base, direct data correlation, matches historical pattern | Multiple data points align, historical precedent exists |
| Medium (50–80%) | Probable cause identified but alternative hypotheses exist | One or two factors align, sample size is adequate but not large |
| Low (<50%) | Insufficient data or multiple competing causes of similar weight | Small sample size, no historical match, conflicting signals |

The agent must never state a root cause with high confidence when the sample size minimum has not been met.

---

## 8. Outputs & Response Formats

### 8.1 Dashboard Metrics (Passive, Always Visible)

The following must always be displayed in the Operations Tower quality panel:

| Metric | Format | Update Frequency |
|---|---|---|
| Blended gold-set accuracy | Percentage (e.g. 96.3%) + color indicator (green/amber/red) | Per evaluation batch |
| Inter-annotator agreement | Krippendorff α value (e.g. 0.91) | Per evaluation cycle |
| Rework rate | Percentage vs. target (e.g. 3.1% / target <4%) | Daily |
| Active drift alerts | Count + severity (e.g. "1 — Pathology, wk5") | Real-time |
| Quality by team | Per-team accuracy table | Per evaluation batch |
| Error taxonomy chart | Category breakdown for current week (bar chart) | Per evaluation batch |
| Gold-set accuracy trend | Week-over-week line chart per team (minimum 6 weeks) | Per evaluation batch |

### 8.2 Drift Alert (Push Notification)

```
⚠ DRIFT ALERT — [Team Name] | [Severity Tier]
Project: [project_id]
Metric: Gold-set accuracy [prior]% → [current]% (W[n-1]→W[n])
Rework rate: [current]% [vs target indicator]
IAA: [prior] → [current]

Root cause: [Primary factor] — [X]% contribution
Evidence: [citations]

Recommended action: [Top action]
Schedule impact: [None / Minor / Moderate / High] — [detail]
Confidence: [Level]

→ View full analysis | → Approve recommended action | → Escalate
```

### 8.3 Conversational Query Response

Natural language responses must follow this structure:

1. **Direct answer** to the query (first sentence, no preamble)
2. **Supporting data** (metrics, trend, breakdown)
3. **Root cause** (if applicable)
4. **Recommended actions** (ranked, with priority)
5. **Confidence level**
6. **Source citations** (data references, SOP IDs, lesson IDs)

The agent must never produce a response that states a problem without also stating at least one recommended action.

### 8.4 Weekly Quality Report (for Client Interaction Agent)

```json
{
  "report_type": "quality_summary",
  "period": "W[n]",
  "project_id": "[id]",
  "overall_status": "on_track | at_risk | critical",
  "gold_set_accuracy_blended": "[value]%",
  "rework_rate": "[value]%",
  "rework_rate_target": "[value]%",
  "iai_score": "[value]",
  "drift_events_this_period": [
    {
      "team": "[team_name]",
      "week": "[n]",
      "status": "detected | resolved | ongoing",
      "resolution_summary": "[plain language]"
    }
  ],
  "client_narrative": "[One paragraph, plain language, no internal identifiers]",
  "confidence": "high | medium | low"
}
```

### 8.5 Lesson Log Entry (for Operational Knowledge Agent)

When a quality event is resolved, the agent must generate a lesson log entry:

```json
{
  "lesson_id": "auto-generated",
  "date": "[ISO date]",
  "project_id": "[id]",
  "team": "[team]",
  "task_type": "[type]",
  "trigger": "[What happened]",
  "root_cause": "[Confirmed root cause]",
  "action_taken": "[What was done]",
  "outcome": "[Metric recovery detail]",
  "sop_updated": true | false,
  "sop_reference": "[id if applicable]",
  "tags": ["[error category]", "[task type]", "[team]"]
}
```

---

## 9. Inter-Agent Interactions

### 9.1 → Delivery Performance Agent (Agent 01)

**Direction:** Quality → Delivery  
**When:** On every drift alert and on every rework rate breach.  
**Payload:**

```json
{
  "signal_type": "quality_risk",
  "project_id": "[id]",
  "team": "[team]",
  "rework_volume_units": "[n]",
  "rework_time_estimate_days": "[n]",
  "severity": "low | medium | high | critical",
  "hold_recommended": true | false,
  "affected_batch_ids": ["[id]"]
}
```

**Purpose:** Delivery Agent adjusts schedule confidence score and throughput forecast. If rework volume is significant, it may trigger an escalation alert and recommend annotator reallocation.

---

### 9.2 → Client Interaction Agent (Agent 05)

**Direction:** Quality → Client Interaction  
**When:** Weekly summary generation cycle, and on any drift alert that affects a client-visible project.  
**Payload:** Weekly Quality Report JSON (see Section 8.4).  
**Purpose:** Client Interaction Agent uses the quality narrative as an input to the executive summary. It does not expose raw quality data to the client directly.

**Important constraint:** The Quality Agent must sanitize all client-facing outputs. No reviewer IDs, no internal SOP identifiers, no raw error counts. Only blended metrics and plain-language narrative.

---

### 9.3 → Workforce & Capability Agent (Agent 03)

**Direction:** Quality → Workforce  
**When:** Root-cause analysis confirms an onboarding gap or skill shortage.  
**Payload:**

```json
{
  "signal_type": "skill_gap",
  "reviewer_ids": ["[id]"],
  "project_id": "[id]",
  "task_type": "[type]",
  "error_category": "[category]",
  "recommendation": "calibration | upskilling | reassignment",
  "urgency": "immediate | this_week | planned"
}
```

**Purpose:** Workforce Agent flags the gap for calibration scheduling, updates skill coverage matrix, and may recommend hiring if the gap is systemic.

---

### 9.4 ↔ Operational Knowledge Agent (Agent 06)

**Direction:** Bidirectional.

**Quality → Knowledge (Read):** When generating root-cause recommendations, the Quality Agent queries the Knowledge Agent for:
- Relevant SOP versions and text
- Historical lesson entries matching the current error pattern (by task type, error category, and team tags)
- Calibration decks for the relevant domain

**Quality → Knowledge (Write):** When a quality event is resolved, the Quality Agent writes a lesson log entry to the Knowledge Agent (see Section 8.5).

**Knowledge → Quality (Passive):** The Knowledge Agent indexes new SOPs and lessons. The Quality Agent's RAG retrieval is automatically updated when new documents are indexed.

---

### 9.5 → Project Governance Agent (Agent 04)

**Direction:** Quality → Governance  
**When:** A drift alert remains unresolved for more than [configurable, default: 5 business days], or when severity is Critical.  
**Payload:**

```json
{
  "signal_type": "quality_escalation",
  "project_id": "[id]",
  "team": "[team]",
  "metric": "[metric name]",
  "current_value": "[value]",
  "floor_threshold": "[value]",
  "days_in_breach": "[n]",
  "recommended_governance_action": "[text]",
  "client_visible": true | false
}
```

**Purpose:** Governance Agent adds a red item to the governance register, tracks owner assignment and resolution, and surfaces it to the client view if warranted.

---

### 9.6 Interaction Summary Diagram

```
[QA Logs / Gold Sets / IAA Records / Scorecards]
                    ↓
        QUALITY INTELLIGENCE AGENT (02)
         ↙          ↓         ↘        ↘
Agent 01      Agent 05    Agent 03   Agent 06
(Delivery)    (Client)    (Workforce) (Knowledge)
  ↓                              ↑
Agent 04 (Governance) ←──────────┘
  (on escalation)
```

---

## 10. Conversational Interaction Patterns

### 10.1 Supported Query Types

The agent must be able to handle queries in these categories:

**Status queries:**
- "What is the current quality status for [project]?"
- "How is [team] performing on quality this week?"
- "Show me the quality dashboard for [project]."

**Diagnostic queries:**
- "Why is [team] accuracy dropping?"
- "What is driving rework on [project]?"
- "Which error categories are increasing?"
- "Why did IAA drop for [task type]?"

**Action queries:**
- "What should I focus on for quality today?"
- "What is the recommended action for the Pathology drift?"
- "How do I fix the boundary precision issues on [project]?"

**Impact queries:**
- "How is this quality issue affecting the delivery schedule?"
- "How many units need re-review?"
- "What is the rework volume impact in days?"

**What-if queries:**
- "If we skip calibration, what happens to rework next week?"
- "What is the recovery time if we run calibration on [date]?"

**Historical queries:**
- "Have we seen this error pattern before?"
- "How was the Pathology drift in W3 resolved?"
- "What does the SOP say about thin-structure boundaries?"

**Report queries:**
- "Generate the quality summary for this week."
- "Give me a client-ready quality narrative for [project]."

### 10.2 Tone and Response Guidelines

- **Be direct:** Lead with the answer, then the evidence. Do not start with "I see that..." or "Based on my analysis..."
- **Be specific:** Always cite the exact metric value, the delta, the date range, and the source.
- **Be actionable:** Every response that identifies a problem must include at least one recommended action.
- **Be honest about uncertainty:** State confidence levels explicitly. Do not speculate beyond what the data supports.
- **Role-aware:** Automatically adjust response detail based on the requesting persona's access level. A Client Stakeholder query must return a narrative response only. A QA Lead query may return reviewer-level detail.

### 10.3 Example Exchanges

**Example 1 — Status query:**

> User: "What is the quality status for the Pathology project?"
>
> Agent: "Pathology gold-set accuracy is 92.0% as of W5 — below the 94% floor. Rework rate is 5.3%, above the 4% target. One drift alert is active. Root cause: boundary precision errors on thin structures, primarily from 3 reviewers onboarded in W3. Calibration session is recommended. Delivery impact: 1.2 days for re-review of 340 affected tiles. Confidence: High."

**Example 2 — What-if query:**

> User: "What if we just re-review the tiles without running calibration?"
>
> Agent: "Without calibration, the 3 reviewers continue annotating with the same gap. Based on their current error rate on thin structures (~18%), new production this week will likely generate 290–380 additional rework tiles by W7. Rework rate will not return below 4% without the calibration step. Recommendation stands: calibration first, then re-review. Skipping calibration resolves the backlog but not the source."

**Example 3 — Historical query:**

> User: "Have we seen this boundary precision pattern before?"
>
> Agent: "Yes. Lesson #1487 (W3) records an identical pattern on Pathology thin structures. The resolution was a 45-minute calibration session using worked examples from SOP-PA-07 §4.2. Accuracy recovered from 91.8% to 96.1% within 1 week. The root cause in that case was also a new reviewer cohort. Lesson #1502 documents a second instance resolved via the same approach."

---

## 11. Business Rules

| Rule ID | Rule | Rationale |
|---|---|---|
| BR-01 | Every drift alert must include a root-cause analysis. The agent must not surface a metric breach without a diagnostic explanation. | Alerts without context create noise and frustration rather than action. |
| BR-02 | Every root-cause conclusion must cite at least one data source. The agent must not speculate beyond what the data supports. | Evidence-backed AI is a core design principle. Hallucinated root causes destroy trust. |
| BR-03 | The agent must not expose reviewer identities to Client Stakeholder personas under any circumstances. | Privacy and professional governance. Reviewer performance is internal information. |
| BR-04 | The agent must state a confidence level with every diagnostic response. | Users must know how much weight to give the agent's conclusion. |
| BR-05 | If minimum sample size is not met, the agent must not issue a root-cause conclusion. It must flag the data gap instead. | Statistical validity. Small samples produce misleading conclusions. |
| BR-06 | Drift alerts that remain unresolved for more than 5 business days must be automatically escalated to the Project Governance Agent. | Unresolved quality issues have compounding delivery impact. Governance must be aware. |
| BR-07 | Client-facing quality narratives must be approved by the Delivery Manager before transmission. The agent drafts; a human approves. | Human-in-the-loop is mandatory for all client-facing communications. |
| BR-08 | Every resolved quality event must generate a lesson log entry in the Operational Knowledge Agent. This is not optional. | Institutional memory requires systematic capture, not manual documentation. |
| BR-09 | The agent must not modify SOP documents directly. It may recommend SOP changes and generate draft amendment text, but a human must author and approve the final update. | SOP changes have operational impact across all projects. Human authorship and approval is required. |
| BR-10 | Gold-set composition and version changes must be tracked. Accuracy drops following a gold-set update must be evaluated against the gold-set change, not assumed to reflect reviewer degradation. | Conflating gold-set version changes with reviewer performance degradation leads to incorrect calibration interventions. |

---

## 12. Thresholds & Alert Conditions

All threshold values below are defaults. They must be configurable per project and per client.

| Metric | Green | Amber (Warning) | Red (Alert) | Critical (Escalate) |
|---|---|---|---|---|
| Gold-set accuracy (blended) | ≥ 96% | 94–95.9% | 92–93.9% | < 92% |
| Week-over-week accuracy drop | < 1% | 1–2% | 2–4% | > 4% |
| Rework rate | < 3% | 3–4% | 4–6% | > 6% |
| IAA (Krippendorff α) | ≥ 0.90 | 0.85–0.89 | 0.80–0.84 | < 0.80 |
| Week-over-week IAA drop | < 0.03 | 0.03–0.05 | 0.05–0.08 | > 0.08 |
| Days drift alert unresolved | — | — | 3–5 days | > 5 days → auto-escalate |

**Rolling trend alert:** If gold-set accuracy shows a declining trend for 3 or more consecutive weeks — even if each individual week's drop is below the single-week threshold — the agent must issue a trend alert at Amber severity.

---

## 13. Error Handling & Edge Cases

| Scenario | Agent Behavior |
|---|---|
| Gold-set data not received for the current evaluation cycle | Flag data gap in dashboard. Do not issue a drift conclusion. Log the gap. Notify Delivery Manager. |
| Reviewer scorecard data has fewer than minimum 50 items | Do not draw reviewer-level conclusions. Aggregate to team level. State the sample size limitation in the response. |
| Gold-set was updated this evaluation cycle | Before comparing accuracy, check whether the gold-set version changed. If yes, flag this as a confounding factor in any accuracy delta analysis. |
| IAA calculation requires 3+ reviewers but only 2 are available for a task type | Do not compute IAA. Flag as "IAA not computable — insufficient reviewers." |
| User asks about a project outside their access scope | Return: "You do not have access to [project]. Contact your Delivery Manager for access." Do not return partial data. |
| Root-cause analysis produces Low confidence | Return the analysis with "Low confidence" explicitly stated and the reason. Do not withhold the response — Low confidence with explanation is more useful than silence. |
| Conflicting signals (e.g. accuracy drops but rework rate improves) | State the conflict explicitly: "Conflicting signals detected — gold-set accuracy has dropped but rework rate is improving. This may indicate a gold-set version change or a task complexity shift. Manual review recommended." |
| What-if query with no historical precedent | State: "No historical precedent found for this scenario. The following projection is based on current error rates only and carries higher uncertainty." |
| Agent retrieval from Knowledge Agent fails | Fall back to available local data. State in the response: "Knowledge base retrieval unavailable. Recommendations are based on direct data analysis only." |

---

## 14. Governance & Security

### 14.1 Role-Based Access Control (RBAC)

| Data Layer | Client | Project Manager | Delivery Manager | QA Lead | Leadership |
|---|---|---|---|---|---|
| Blended quality metrics | ✓ (narrative) | ✓ (their projects) | ✓ (all) | ✓ (all) | ✓ (aggregate) |
| Per-team accuracy breakdown | ✗ | ✓ (their projects) | ✓ | ✓ | ✓ (aggregate) |
| Per-reviewer scorecard | ✗ | ✗ | ✓ | ✓ | ✗ |
| Error taxonomy detail | ✗ (narrative only) | ✓ (their projects) | ✓ | ✓ | ✓ (aggregate) |
| Raw QA logs | ✗ | ✗ | ✓ | ✓ | ✗ |
| Drift alert detail | ✗ (narrative only) | ✓ (their projects) | ✓ | ✓ | ✓ (summary) |
| Cross-client trends | ✗ | ✗ | ✗ | ✗ | ✓ |

### 14.2 Audit Trail Requirements

Every agent action must be logged:

- Query text and timestamp
- Requesting persona and user ID
- Data sources accessed
- Response generated
- Any downstream agent signals sent (type, payload, timestamp)

Audit logs must be immutable and retained for a minimum of 24 months for regulated projects.

### 14.3 Data Governance

- Client data must be tenant-isolated. The agent must not mix data across client boundaries under any circumstances.
- All quality data used by the agent must have passed through the Unified Data Foundation normalization layer before ingestion.
- The agent must not ingest raw unvalidated data directly from source systems.
- Synthetic or anonymized data must be used in development and testing environments. No production client data in dev.

---

## 15. Success Metrics

### 15.1 Quality Outcome Metrics

| Metric | Target |
|---|---|
| Rework rate across active projects | < 4% sustained |
| Drift detection lead time | Alert fires before client-visible impact 90% of the time |
| Drift resolution time | Average < 5 business days from alert to accuracy recovery |
| False positive alert rate | < 10% (alerts that trigger but are not confirmed quality issues) |

### 15.2 Agent Performance Metrics

| Metric | Target |
|---|---|
| Root-cause diagnosis accuracy | Confirmed correct by QA Lead > 80% of cases |
| Response latency (conversational) | < 3 seconds for standard queries |
| Response latency (root-cause analysis) | < 10 seconds |
| Recommended action adoption rate | QA Lead acts on agent recommendation > 70% of the time |
| Lesson log capture rate | 100% of resolved quality events generate a lesson entry |

### 15.3 User Experience Metrics

| Metric | Target |
|---|---|
| QA Lead time to reach diagnosis (with agent vs. without) | > 50% reduction |
| Manual QA report preparation time | > 60% reduction vs. pre-agent baseline |
| Delivery Manager confidence in quality data | Measured via internal NPS; target > 4.0/5.0 |

---

## 16. Implementation Notes

### 16.1 Architecture Dependencies

The following must be in place before this agent can be built:

1. **Unified Data Foundation (Layer 1)** — structured data normalization and KPI semantic model. The agent cannot function without a consistent, validated data source.
2. **Operational Knowledge Agent (Agent 06)** — the lesson retrieval and SOP lookup capability is a hard dependency for root-cause recommendation quality.
3. **Operations Tower RBAC layer** — persona-aware response filtering must be implemented at the platform level, not within this agent alone.
4. **Error taxonomy schema** — must be finalized and agreed with QA Leads before agent development begins. Taxonomy changes after launch require agent update.

### 16.2 Build Priority Within This Agent

Implement in this order:

1. Dashboard metrics display (passive, read-only quality KPIs from existing data)
2. Automated drift alert logic (threshold breach detection, push notification)
3. Root-cause reasoning for common cases (onboarding gap and SOP ambiguity hypotheses first — these cover the majority of real-world cases)
4. Conversational query interface (status and diagnostic query types first)
5. Inter-agent signal emission (Delivery Agent and Workforce Agent integrations)
6. Client narrative generation (Client Interaction Agent integration)
7. What-if scenario analysis (most complex reasoning, build last)
8. Lesson log write-back to Knowledge Agent

### 16.3 Open Questions (To Be Resolved Before Build)

The following are unresolved at the time of this document's writing:

- **Threshold configurability:** Are thresholds set per client, per vertical, or per task type? Who has permission to change them?
- **Gold-set ownership:** Who owns gold-set updates? What is the approval process? This affects how the agent handles gold-set version change events.
- **LLM vendor:** The conversational interface and root-cause reasoning layer require an LLM. Vendor is not yet decided (in-house vs. API provider).
- **Real-time vs. batch:** Are gold-set evaluations run continuously or in batches? This determines whether drift detection is real-time or cycle-based.
- **SLA definitions:** The client-facing SLA for quality (e.g. "we commit to X% gold-set accuracy") is not defined in current documentation. This directly affects what threshold triggers a client-visible event.

### 16.4 Testing Requirements

Before production deployment:

- Run agent against synthetic datasets with known quality drift events. Agent must correctly detect and diagnose 90% of injected drift scenarios.
- Test RBAC by querying with each persona type. Verify no cross-persona data leakage.
- Validate root-cause reasoning against 10+ historical real quality events where root cause is already known.
- Load test conversational interface for concurrent users (minimum 20 simultaneous sessions without latency degradation).
- Have QA Lead review 20 agent-generated recommendations blind (not knowing which are agent-generated) and rate accuracy.

---

*Document prepared for implementation use. Questions or clarifications should be directed to the project lead before build begins. All threshold values and business rules should be validated with QA Leads and Delivery Managers before finalizing.*
