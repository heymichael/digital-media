-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Migration tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT now(),
    applied_by TEXT
);

-- Core asset table
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_slug TEXT NOT NULL,
    
    -- Storage
    gcs_bucket TEXT NOT NULL,
    gcs_path TEXT NOT NULL,
    
    -- Metadata
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    width INT,
    height INT,
    
    -- Editable fields
    title TEXT,
    alt_text TEXT,
    description TEXT,
    approved_public BOOLEAN DEFAULT FALSE,
    
    -- Audit
    uploaded_by TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    
    UNIQUE(org_slug, gcs_path)
);

CREATE INDEX idx_assets_org ON assets(org_slug) WHERE deleted_at IS NULL;
CREATE INDEX idx_assets_created ON assets(org_slug, created_at DESC) WHERE deleted_at IS NULL;

-- Tags (manual + auto)
CREATE TABLE asset_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('manual', 'auto')),
    confidence REAL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(asset_id, tag)
);

CREATE INDEX idx_asset_tags_tag ON asset_tags(tag);
CREATE INDEX idx_asset_tags_asset ON asset_tags(asset_id);

-- Full-text search
ALTER TABLE assets ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(filename, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(alt_text, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'D')
    ) STORED;

CREATE INDEX idx_assets_search ON assets USING GIN(search_vector);

-- Vector embeddings
CREATE TABLE asset_embeddings (
    asset_id UUID PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_embeddings_vector ON asset_embeddings 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Generic references (consumers register usage)
CREATE TABLE asset_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    consumer_type TEXT NOT NULL,  -- e.g., 'cms', 'website', 'docs'
    consumer_id TEXT NOT NULL,    -- e.g., page ID, doc ID
    consumer_field TEXT,          -- e.g., 'hero_image', 'gallery[2]'
    org_slug TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(asset_id, consumer_type, consumer_id, consumer_field)
);

CREATE INDEX idx_refs_asset ON asset_references(asset_id);
CREATE INDEX idx_refs_consumer ON asset_references(consumer_type, consumer_id);
