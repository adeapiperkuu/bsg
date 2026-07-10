ALTER TABLE public.knowledge_query_feedback
  ADD COLUMN IF NOT EXISTS feedback_reason text,
  ADD COLUMN IF NOT EXISTS answer_confidence double precision,
  ADD COLUMN IF NOT EXISTS query_type text,
  ADD COLUMN IF NOT EXISTS selected_source_ids jsonb;

CREATE INDEX IF NOT EXISTS knowledge_query_feedback_reason_idx
  ON public.knowledge_query_feedback (org_id, feedback_reason);
