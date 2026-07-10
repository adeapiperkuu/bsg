-- Phase 4 retrieval tuning settings for the Operational Knowledge Agent.

ALTER TABLE public.knowledge_retrieval_settings
  ADD COLUMN IF NOT EXISTS min_relevance double precision NOT NULL DEFAULT 0.25,
  ADD COLUMN IF NOT EXISTS max_candidates integer NOT NULL DEFAULT 20,
  ADD COLUMN IF NOT EXISTS source_types jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS folder_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS recency_preference double precision NOT NULL DEFAULT 0.5,
  ADD COLUMN IF NOT EXISTS exact_term_preference double precision NOT NULL DEFAULT 0.5;

ALTER TABLE public.knowledge_retrieval_settings
  DROP CONSTRAINT IF EXISTS knowledge_retrieval_settings_min_relevance_check,
  ADD CONSTRAINT knowledge_retrieval_settings_min_relevance_check
    CHECK (min_relevance >= 0 AND min_relevance <= 1);

ALTER TABLE public.knowledge_retrieval_settings
  DROP CONSTRAINT IF EXISTS knowledge_retrieval_settings_min_confidence_check,
  ADD CONSTRAINT knowledge_retrieval_settings_min_confidence_check
    CHECK (min_confidence >= 0 AND min_confidence <= 1);

ALTER TABLE public.knowledge_retrieval_settings
  DROP CONSTRAINT IF EXISTS knowledge_retrieval_settings_max_candidates_check,
  ADD CONSTRAINT knowledge_retrieval_settings_max_candidates_check
    CHECK (max_candidates >= max_sources);

ALTER TABLE public.knowledge_retrieval_settings
  DROP CONSTRAINT IF EXISTS knowledge_retrieval_settings_recency_preference_check,
  ADD CONSTRAINT knowledge_retrieval_settings_recency_preference_check
    CHECK (recency_preference >= 0 AND recency_preference <= 1);

ALTER TABLE public.knowledge_retrieval_settings
  DROP CONSTRAINT IF EXISTS knowledge_retrieval_settings_exact_term_preference_check,
  ADD CONSTRAINT knowledge_retrieval_settings_exact_term_preference_check
    CHECK (exact_term_preference >= 0 AND exact_term_preference <= 1);

UPDATE public.knowledge_retrieval_settings
SET only_approved = true,
    min_relevance = COALESCE(min_relevance, min_confidence, 0.25),
    max_candidates = GREATEST(max_candidates, max_sources);
