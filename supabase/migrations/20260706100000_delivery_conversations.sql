-- Delivery Agent persistent conversation history

CREATE TABLE delivery_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organisations (id) ON DELETE RESTRICT,
  user_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  project_id UUID REFERENCES projects (id) ON DELETE SET NULL,
  title TEXT NOT NULL DEFAULT 'New conversation',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX delivery_conversations_user_updated_idx
  ON delivery_conversations (user_id, updated_at DESC);

CREATE INDEX delivery_conversations_org_user_project_updated_idx
  ON delivery_conversations (org_id, user_id, project_id, updated_at DESC);

CREATE TRIGGER delivery_conversations_updated_at
  BEFORE UPDATE ON delivery_conversations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE delivery_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES delivery_conversations (id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  agent_query_id UUID REFERENCES agent_queries (id) ON DELETE SET NULL,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX delivery_messages_conversation_created_idx
  ON delivery_messages (conversation_id, created_at);

ALTER TABLE delivery_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY delivery_conversations_owner_select ON delivery_conversations FOR SELECT TO public
  USING (user_id = current_user_id());

CREATE POLICY delivery_conversations_owner_insert ON delivery_conversations FOR INSERT TO public
  WITH CHECK (user_id = current_user_id());

CREATE POLICY delivery_conversations_owner_update ON delivery_conversations FOR UPDATE TO public
  USING (user_id = current_user_id());

CREATE POLICY delivery_conversations_owner_delete ON delivery_conversations FOR DELETE TO public
  USING (user_id = current_user_id());

CREATE POLICY delivery_messages_owner_select ON delivery_messages FOR SELECT TO public
  USING (
    EXISTS (
      SELECT 1
      FROM delivery_conversations dc
      WHERE dc.id = delivery_messages.conversation_id
        AND dc.user_id = current_user_id()
    )
  );

CREATE POLICY delivery_messages_owner_insert ON delivery_messages FOR INSERT TO public
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM delivery_conversations dc
      WHERE dc.id = delivery_messages.conversation_id
        AND dc.user_id = current_user_id()
    )
  );

CREATE POLICY delivery_messages_owner_delete ON delivery_messages FOR DELETE TO public
  USING (
    EXISTS (
      SELECT 1
      FROM delivery_conversations dc
      WHERE dc.id = delivery_messages.conversation_id
        AND dc.user_id = current_user_id()
    )
  );
