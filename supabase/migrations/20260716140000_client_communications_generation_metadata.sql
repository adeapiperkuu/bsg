-- Additive generation metadata for PM report drafts (Phase 4).
-- generation_mode: 'ai' | 'fallback'; generation_warning: optional user-facing notice.

ALTER TABLE client_communications
  ADD COLUMN IF NOT EXISTS generation_mode TEXT;

ALTER TABLE client_communications
  ADD COLUMN IF NOT EXISTS generation_warning TEXT;
