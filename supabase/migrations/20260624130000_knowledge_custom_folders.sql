-- Allow unlimited knowledge folders per organisation.

ALTER TYPE knowledge_folder_kind ADD VALUE IF NOT EXISTS 'custom';

ALTER TABLE knowledge_folders DROP CONSTRAINT IF EXISTS knowledge_folders_org_kind_key;

CREATE UNIQUE INDEX IF NOT EXISTS knowledge_folders_org_name_key
  ON knowledge_folders (org_id, lower(name))
  WHERE deleted_at IS NULL;
