-- schema.sql
-- FIX: Generic SQL document store used by the bot runtime.

CREATE TABLE IF NOT EXISTS documents (
    collection_path TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (collection_path, doc_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_collection_path ON documents (collection_path);
CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_doc_id ON documents (doc_id);

COMMENT ON TABLE documents IS 'Generic document store backing bot users, payments, battles, caches, and content.';
COMMENT ON COLUMN documents.collection_path IS 'Firestore-style collection path, for example users or users/123/wrong_questions.';
COMMENT ON COLUMN documents.doc_id IS 'Document identifier inside the collection path.';
COMMENT ON COLUMN documents.data IS 'JSON document payload stored by the bot.';
