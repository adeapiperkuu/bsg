-- Group knowledge agent turns into persisted conversations
ALTER TABLE agent_queries
  ADD COLUMN IF NOT EXISTS conversation_id UUID REFERENCES agent_queries(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS agent_queries_conversation_created_idx
  ON agent_queries (conversation_id, created_at);
