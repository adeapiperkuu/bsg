# Governance AI Recommendations

Governance recommendations are grounded, persisted AI guidance with a deterministic operational
fallback. Generation is explicit and runs as a durable background job; dashboard reads never call
the model.

## Architecture

```text
Governance data
  -> rule-based signal candidates
  -> scoped evidence bundle
  -> explicit background generation job
  -> structured LLM generation
  -> schema and grounding validation
  -> duplicate checks
  -> persist governance_ai_recommendations
  -> dashboard reads persisted rows
  -> optional reviewed conversion to action or escalation
```

The analytics detail path can build rule-based recommendations synchronously, but it does not call
the LLM. AI generation never runs on dashboard load or hover prefetch.

## Sources and fallback

| Source | When | Label |
|---|---|---|
| AI | Valid persisted rows after explicit generation | `AI Generated` |
| Rule-based | Analytics detail or generation fallback | `Rule-based` |

Fallback order is persisted AI for current evidence, newly generated valid AI, rule-based guidance,
then the empty state.

## Generation flow

1. `POST /governance/ai-recommendations/generate` returns `202` and a job ID.
2. The worker assembles scoped evidence and deterministic signals.
3. The worker calls structured generation with `prompts/ai_recommendations.md`.
4. Schema and evidence grounding are validated.
5. Valid recommendations are persisted and audited before the job succeeds.
6. React Query refreshes the recommendation list after successful completion.

## Review and conversion

Recommendations never create actions or escalations automatically. A user must review a
recommendation and explicitly confirm conversion. Conversion records retain source and evidence
traceability and remain idempotent.

## Current API

- `POST /governance/ai-recommendations/generate`
- `POST /governance/ai-recommendations/{id}/regenerate`
- `GET /governance/ai-recommendations`
- `POST /governance/ai-recommendations/{id}/dismiss`
- `POST /governance/ai-recommendations/{id}/feedback`
- `POST /governance/ai-recommendations/{id}/convert/action`
- `POST /governance/ai-recommendations/{id}/convert/escalation`

## Performance

- The Governance route imports its dashboard directly, avoiding an additional lazy-chunk waterfall.
- Bootstrap and the active primary table start immediately.
- Cached data uses long stale windows and `keepPreviousData` where appropriate.
- Recommendation generation and provider latency stay outside request handling.

## Related

- Durable jobs: `docs/governance-background-jobs.md`
- Recommendation effectiveness: `docs/governance-recommendation-effectiveness.md`
- Controlled optimization: `docs/governance-recommendation-optimization.md`
