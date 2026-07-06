# Quality Intelligence Agent — LLM Reasoning Upgrade Plan

**Agent ID:** 02
**Document version:** 1.0
**Status:** Proposed (planning)
**Related:**
- Full spec: [`docs/AI Agents/quality_intelligence_agent_v1_0.md`](../AI%20Agents/quality_intelligence_agent_v1_0.md)
- Roadmap: [`docs/agents/quality_intelligence_roadmap.md`](./quality_intelligence_roadmap.md)
- Gap tracker: [`backend/app/agents/QUALITY_INTELLIGENCE_V1_GAPS.md`](../../backend/app/agents/QUALITY_INTELLIGENCE_V1_GAPS.md)

---

## 0. The core problem, restated precisely

Today the pipeline is **rules decide → LLM narrates**:

```
snapshot → root_cause.py (6 hardcoded SQL+threshold branches, magic-number %s)
        → JSON verdict
        → query_handler.py dumps verdict into prompt
        → LLM rephrases into prose (never sees raw data)
        → citations.py strips anything the LLM added
```

The LLM is structurally forbidden from reasoning. It cannot weigh competing
hypotheses, cannot discover a cause nobody coded a branch for, and its
"confidence" is just a bucket test on a hardcoded arithmetic score
(`backend/app/agents/quality_intelligence/root_cause.py:381-386`).

The target is **evidence → LLM reasons → rules validate**:

```
snapshot → evidence_pack.py (ALL raw slices, anonymized, bounded, each cited)
        → feature extractors emit SIGNALS (facts, not verdicts)
        → reasoning.py: LLM weighs hypotheses over the real data → structured JSON
        → validation layer: citations grounded? confidence vs sample size? % sums? PII?
        → deterministic engine as FALLBACK + shadow comparison
        → synthesis prompt → §8.3 response
```

The repo already contains the pattern to copy: the **Delivery Agent**
(`_DELIVERY_SYSTEM_PROMPT` in `backend/app/services/llm/client.py:209` +
`_build_context` in `backend/app/agents/delivery/services/chat_service.py:258`)
hands the LLM a structured context of live signals and lets it interpret, rank,
and recommend — with anti-fabrication guardrails. We bring Quality up to that
bar, then past it (Quality has richer structured data: scorecards, IAA, SOP
timelines, gold-set versions).

**Design invariant:** we must not regress the guarantees the deterministic
engine currently enforces — BR-02 (every claim cited), BR-03 (no reviewer IDs to
clients), BR-04 (confidence always stated), BR-05 (sample-size gate). This plan
keeps all four, but moves them from "the rules are the only reasoner" to "the
rules are the guardrail around a reasoner."

---

## 1. New module: `evidence_pack.py` (the biggest change)

Right now `gather_quality_evidence`
(`backend/app/agents/quality_intelligence/query_handler.py:78`) fetches only 6
snapshots + errors + 5 alerts. Meanwhile `root_cause.py` separately fetches
scorecards, eval logs, IAA, SOP history, gold-set metadata, throughput —
**reduces each to a boolean/threshold — and throws the raw data away.** The LLM
never sees any of it.

Create `backend/app/agents/quality_intelligence/evidence_pack.py`:

```python
@dataclass(frozen=True)
class EvidenceItem:
    key: str            # stable ref the LLM cites, e.g. "SNAP-W5", "R3", "SOP-12"
    source_table: str
    source_row_id: UUID
    summary: str        # compact human/LLM-readable line
    data: dict          # structured fields

@dataclass(frozen=True)
class EvidencePack:
    snapshot_timeline: list[EvidenceItem]     # 8-12 wks: acc, IAA, rework, drift flag
    error_taxonomy_trend: dict                # per-category share by week (trend, not point)
    reviewer_scorecards: list[EvidenceItem]   # anonymized R1..Rn: accuracy, err breakdown, items
    eval_log_rollup: dict                     # per-reviewer / per-category from gold_set_evaluation_logs
    iaa_records: list[EvidenceItem]           # per task-type, per pair, alpha + delta
    sop_timeline: list[EvidenceItem]          # version, effective_date, change_summary
    gold_set_versions: list[EvidenceItem]     # version changes (BR-10 confounder)
    throughput_timeline: list[EvidenceItem]   # utilization/fatigue signal
    onboarding_events: list[EvidenceItem]     # who joined when (windowed)
    open_alerts: list[EvidenceItem]
    oka_lessons: list[dict]                   # retrieved by task_type/error_category/team
    key_index: dict[str, EvidenceItem]        # key -> item, for citation validation
```

Rules that make this safe and affordable:

- **Anonymize at the source.** Reviewers become stable handles `R1, R2…` keyed
  off `annotator_id`, with a private `key_index` mapping kept server-side and
  never sent to the model. The *pack itself* is client-safe by construction —
  the LLM can reason about "error concentration in R3/R7" without any PII ever
  entering the prompt. This fixes the current approach where
  `filter_context_for_role` (`backend/app/services/quality_scoping.py:40`) just
  *deletes* any line containing "reviewer", which for a client blinds the model
  entirely.
- **Bound the token budget.** Snapshots capped at 12 weeks; scorecards to top-N
  by error contribution; every free-text field truncated (reuse the
  `_truncate_chunk_text` idea from `backend/app/services/llm/client.py:89`).
  Emit compact `summary` lines, not raw ORM dumps.
- **Every item carries `source_table` + `source_row_id`** so citations stay
  grounded end-to-end (BR-02) and flow into `AgentQueryEvidenceLink` exactly as
  today.

This module replaces both `gather_quality_evidence` and the scattered
`select(...)` calls inside `root_cause.py`.

---

## 2. Refactor `root_cause.py`: verdicts → cited signals + deterministic fallback

The six `_hypothesis_*` functions stay, but change contract. Today
`_hypothesis_eval_log_reviewers` returns
`{"factor": "onboarding_gap", "contribution_pct": min(90, 50 + n*10), ...}` — a
**fabricated weight**. That number is invented, not measured.

Change them to return **signals (facts), not weighted verdicts**:

```python
@dataclass(frozen=True)
class Signal:
    hypothesis: str            # "onboarding_gap"
    observed: bool
    strength: str              # "strong" | "moderate" | "weak" (from data shape, not %)
    facts: list[str]           # "3 reviewers <85% over 50+ items (avg 81.2%)"
    evidence_keys: list[str]   # ["R3","R7","R9"] -> validated against the pack
```

Then:

- **`extract_signals(pack) -> list[Signal]`** — deterministic feature
  extraction. No magic percentages; the *LLM* assigns contribution weights
  during reasoning.
- **`analyze_root_cause_deterministic(...)`** — today's `analyze_root_cause`,
  renamed, kept verbatim as the **fallback** when the LLM is unavailable/invalid
  and for shadow comparison. Guarantees we never do worse than today.
- Keep `_build_recommendations` as the fallback template only (see §5).

Keep the sample-size gate (`root_cause.py:262`) exactly — it runs **before** any
LLM call so BR-05 is enforced structurally: below `MIN_EVALUATED_ITEMS` we never
ask the model for a conclusion.

---

## 3. New module: `reasoning.py` (the LLM reasoning core)

```python
async def reason_root_cause(
    session, snapshot, pack: EvidencePack, signals: list[Signal],
) -> RootCauseResult:
```

Flow:

1. If `settings.quality_llm_reasoning` is off **or** no API key **or**
   sample-size gate tripped → return `analyze_root_cause_deterministic(...)`.
   (dark-launch + safety)
2. Build the reasoning prompt (§4): system = analyst persona; user = the
   evidence pack + extracted signals + the §7.2 hypothesis methodology + §12
   thresholds as *domain knowledge*.
3. Call `LLMClient.generate_structured(system, user, context=pack_json,
   json_mode=True)`.
4. Parse into a strict Pydantic schema:

```python
class LLMFactor(BaseModel):
    factor: str
    contribution_pct: float
    evidence_keys: list[str]
    reasoning: str                    # WHY this factor, from the data
class LLMRootCause(BaseModel):
    primary_driver: str
    factors: list[LLMFactor]
    confidence: Literal["high","medium","low"]
    competing_hypotheses_ruled_out: list[str]
    novel_findings: list[str]         # causes OUTSIDE the six branches, if data supports
    recommended_actions: list[RecommendedAction]
    data_gaps: list[str]
```

5. **Validation layer** (§6) keeps the LLM honest. On any failure → fall back to
   deterministic result, tagged `engine="deterministic_fallback"`.
6. Return unified `RootCauseResult` (extend the existing dataclass with
   `engine`, `novel_findings`, `reasoning_trace`).

The two payoffs the rules cannot give: the model can **rule out confounders**
(e.g. "accuracy dropped but a gold-set version change on the same date explains
it — do NOT trigger reviewer calibration," which is literally BR-10 / the §13
conflicting-signals edge case, currently unhandled by the hardcoded waterfall),
and it can flag **`novel_findings`** — a real cause that no branch covers,
instead of today's `"undetermined"` dead-end (`root_cause.py:361-368`).

---

## 4. Rewrite `prompts.py` — analyst reasoning + synthesis

Replace the 18-line "synthesize the pre-computed analysis" prompt with two
prompts, modeled on `_DELIVERY_SYSTEM_PROMPT`:

**`QUALITY_REASONING_PROMPT`** (new, for §3): casts the model as a *Quality
Intelligence Analyst*, gives it:

- The §7.2 six-hypothesis **methodology** (so it reasons *with* the domain
  method, not from scratch) and the evaluation order.
- The §12 threshold table as reference values.
- Hard grounding rules copied from Delivery: cite only `evidence_keys` present
  in the pack; never invent reviewer handles, SOP IDs, or metrics; if signals
  conflict, say so and lower confidence; never claim "high" confidence below the
  sample-size minimum; assign `contribution_pct` from evidence weight and make
  them sum to ~100.
- Explicit instruction to populate `novel_findings` when the data points outside
  the six hypotheses.
- Strict JSON output shape (matches `LLMRootCause`).

**`QUALITY_SYNTHESIS_PROMPT`** (evolves the current one): turns the *validated*
reasoning object into the §8.3 6-part response (direct answer → data → root
cause → ranked actions → confidence → citations). This is the only step that
produces prose.

---

## 5. LLM-generated recommendations (with fallback)

`_build_recommendations` (`root_cause.py:398`) returns identical canned text per
driver. Move recommendation generation into the reasoning call: the model
produces the §7.4 structure (action / target / expected_outcome / effort /
evidence_basis / priority) grounded in the actual dominant error category, the
specific reviewers, and retrieved **OKA lessons** (so "Lesson #1487 resolved
this via SOP-PA-07 §4.2" becomes real retrieval, not a hardcoded string).
Validate that `evidence_basis` references a real lesson/SOP in the pack; keep
the hardcoded template as fallback.

---

## 6. Extend `citations.py` into a real validation layer

Today it only regex-strips UUIDs not in the evidence set (`citations.py:20`).
Extend to validate the **structured reasoning object**:

- `validate_reasoning(llm_out: LLMRootCause, pack) -> (ok, cleaned, reasons)`:
  - Every `evidence_keys` entry ∈ `pack.key_index` (drop unknowns; if the
    *primary driver's* citations all vanish → reject → fallback).
  - `sum(contribution_pct)` ∈ [90, 110]; else renormalize or reject.
  - `confidence == "high"` requires sample ≥ min AND primary factor > 50% — else
    downgrade (enforces §7.5 / BR-04).
  - No raw `annotator_id`/`reviewer_id` UUIDs leaked (they should not exist —
    pack is anonymized — but assert it; belt-and-suspenders for BR-03).
- Keep `strip_ungrounded_citations` / `append_evidence_index` for the final
  prose pass.

Rejection is not failure — it is the guardrail. A rejected LLM result
deterministically falls back, and we log *why* (audit trail, §14.2).

---

## 7. Rewrite `what_if.py` reasoning

Currently: keyword→bucket→hardcoded projection string, LLM optionally rephrases
(`what_if.py:46-78`). Change to: the LLM reasons over **actual historical
recovery patterns** (snapshot deltas after past interventions + OKA lessons) to
produce a quantified projection with explicit assumptions and a confidence
range, matching §8's Example-2 style. Keep `WhatIfEngine.rule_projection` as the
labeled fallback and for the no-precedent §13 case.

---

## 8. Rewire `query_handler.py`

`answer_quality_query` (`query_handler.py:222`) changes from "dump pre-computed
JSON" to:

1. `pack = await build_evidence_pack(session, project, role=current_user.role)`
   (anonymized per role).
2. `signals = extract_signals(pack)`.
3. `reasoning = await reason_root_cause(session, latest, pack, signals)` —
   cached on `quality_snapshots.root_cause` JSONB, recomputed only when snapshot
   data changes (cost control).
4. Intent branches (`impact`/`historical`/`what_if`) feed their slices **into
   the pack**, not into a separate `analysis_summary` string.
5. Synthesis LLM call over the *validated* reasoning + pack.
6. Existing tail (citation strip, role filter, `AgentQueryEvidenceLink`
   persistence) unchanged.

Drift detection (`drift.py`) **stays deterministic** — threshold breach is a
measurement, not a judgment, and §12/BR rules require exactness. The reasoning
happens downstream on the "why," not the "whether."

---

## 9. Config, model, cost/latency

- Add to `backend/app/core/config.py`: `quality_llm_reasoning: bool = False`
  (dark-launch flag, mirrors `llm_intent_routing`), optional
  `quality_reasoning_model` override.
- `gpt-4o-mini` (current default, `client.py:409`) is weak for multi-hypothesis
  weighing — recommend a stronger model for the *reasoning* call while keeping
  mini for synthesis/intent. Temperature 0.2.
- **Latency budget:** spec §15.2 says root-cause < 10s. One reasoning call + one
  synthesis call fits, but cache aggressively (step 3 above) and only recompute
  reasoning on data change — most conversational queries reuse the stored trace
  and cost just the synthesis call.

---

## 10. Audit trail + shadow rollout (safe migration)

- **Store the reasoning trace**: extend `quality_snapshots.root_cause` JSONB (or
  add `quality_reasoning_runs` table) with `engine`
  (llm/deterministic/fallback), `factors`, `validation_result`, `model_used`,
  `latency_ms` — satisfies §14.2 audit requirements.
- **Shadow mode**: with the flag off, run *both* engines and log divergence (no
  user impact). Gives real data on how often the LLM finds something the rules
  miss, and where it disagrees, before flipping the flag.
- Roll out per-org via the flag.

---

## 11. Testing

- Make existing `backend/tests/test_quality_acceptance.py` hermetic by
  **mocking `LLMClient.generate_structured`** to return canned `LLMRootCause`
  JSON — keeps the ≥90% synthetic-drift gate deterministic.
- New tests: evidence-pack completeness & anonymization (no UUIDs for client
  role); validation layer (renormalize %s, drop bad citations, downgrade
  over-confidence, reject → fallback); fallback path when LLM raises; the §13
  gold-set-confounder case (accuracy down + version change → *not* a calibration
  recommendation).
- Golden set: the spec §16.4 "10+ historical events with known root cause" —
  feed each, assert `primary_driver` matches. This is the acceptance bar for
  shipping.

---

## Files touched

| File | Change |
|---|---|
| `evidence_pack.py` | **new** — comprehensive, anonymized, bounded, cited evidence |
| `reasoning.py` | **new** — LLM reasoning core + fallback orchestration |
| `root_cause.py` | refactor: `_hypothesis_*` → `Signal`s; keep `analyze_root_cause_deterministic` as fallback |
| `prompts.py` | rewrite: `QUALITY_REASONING_PROMPT` + `QUALITY_SYNTHESIS_PROMPT` |
| `citations.py` | extend into structured `validate_reasoning` |
| `query_handler.py` | rewire to pack → signals → reason → synthesize |
| `what_if.py` | LLM reasons over historical patterns; rule projection as fallback |
| `schemas/domain.py` | add `LLMRootCause`, `LLMFactor`, `RecommendedAction` |
| `config.py` | `quality_llm_reasoning` flag + optional reasoning model |
| `services/llm/client.py` | (optional) dedicated `generate_reasoning` helper |
| tests | mock LLM, validation tests, golden historical set |

---

## Sequencing (each step shippable)

1. `evidence_pack.py` + anonymization + tests (no behavior change yet)
2. `root_cause.py` → signals; keep deterministic path as default
3. `reasoning.py` + prompts + schema + validation, behind
   `quality_llm_reasoning=false`
4. Shadow mode: log LLM-vs-deterministic divergence
5. `query_handler.py` rewire; flip flag per-org after golden-set passes
6. `what_if.py` upgrade
7. Audit trace persistence + roadmap / GAPS wording update

**Net effect:** the agent gains genuine reasoning — weighing evidence, ruling
out confounders, surfacing causes outside the six coded branches — while the
deterministic engine becomes the guardrail and fallback, so grounding,
confidence discipline, PII safety, and the sample-size gate are all *stronger*,
not weaker.

---

## Doc-accuracy note

`docs/agents/quality_intelligence_roadmap.md` and
`backend/app/agents/QUALITY_INTELLIGENCE_V1_GAPS.md` currently claim "full
six-hypothesis reasoning complete." That is true for the *rule engine* but
misleading about *reasoning* — the current LLM does not reason over data, it
only narrates a pre-computed verdict. Update that wording as part of step 7.
