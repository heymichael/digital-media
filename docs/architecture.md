# Digital Media Service Architecture

## Overview

The Digital Media service is a standalone asset management system for the Haderach platform. It provides image upload, storage, metadata management, search (full-text and semantic), and reference tracking.

## Repository Layout

```
digital-media/
├── .cursor/rules/          # Cursor rules for AI assistance
├── .github/workflows/      # CI, migrations, deployment
├── docs/
│   └── architecture.md     # This file
├── migrations/             # SQL migrations (applied via CI)
├── scripts/                # Local dev helpers
├── service/
│   ├── app.py             # FastAPI entry point
│   ├── auth.py            # Firebase token verification
│   ├── config.py          # Settings from environment
│   ├── db.py              # Postgres connection pool + queries
│   ├── embeddings.py      # Vertex AI embedding client
│   ├── models.py          # Pydantic request/response schemas
│   ├── storage.py         # GCS signed URL helpers
│   └── tagging.py         # Vision API auto-tagging
├── tests/                  # pytest test suite
├── Dockerfile
├── docker-compose.local.yml
├── requirements.txt
└── README.md
```

## Service Boundaries

| Component | Responsibility |
|-----------|----------------|
| Digital Media API | Asset CRUD, search, reference tracking |
| Cloud SQL Postgres | Asset metadata, tags, embeddings, references |
| GCS (bucket-per-org) | Binary storage (images) |
| Vertex AI | Text embeddings for semantic search |
| Vision API | Auto-tagging on upload |

External consumers (CMS, frontend apps, agent tools) access assets exclusively through the API. Direct database or GCS access is prohibited.

## Database Schema

### `assets`

Primary asset record.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| org_slug | TEXT | Tenant isolation |
| gcs_bucket | TEXT | Storage bucket |
| gcs_path | TEXT | Object path |
| filename | TEXT | Original filename |
| content_type | TEXT | MIME type |
| size_bytes | BIGINT | File size |
| width, height | INT | Image dimensions (nullable) |
| title | TEXT | Editable display title |
| alt_text | TEXT | Accessibility text |
| description | TEXT | Caption/description |
| approved_public | BOOLEAN | Safe for public use |
| uploaded_by | TEXT | Uploader email |
| created_at | TIMESTAMPTZ | Upload timestamp |
| updated_at | TIMESTAMPTZ | Last edit |
| deleted_at | TIMESTAMPTZ | Soft delete marker |
| search_vector | TSVECTOR | Full-text search (generated) |

### `asset_tags`

Manual and auto-generated tags.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| asset_id | UUID | FK to assets |
| tag | TEXT | Tag value |
| source | TEXT | 'manual' or 'auto' |
| confidence | REAL | Auto-tag confidence (nullable) |

### `asset_embeddings`

Semantic search vectors.

| Column | Type | Description |
|--------|------|-------------|
| asset_id | UUID | PK, FK to assets |
| embedding | vector(768) | Vertex AI embedding |
| model | TEXT | Model version |

### `asset_references`

Generic usage tracking for consumers.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| asset_id | UUID | FK to assets |
| consumer_type | TEXT | e.g., 'cms', 'website' |
| consumer_id | TEXT | e.g., page ID |
| consumer_field | TEXT | e.g., 'hero_image' |
| org_slug | TEXT | Tenant isolation |

## Storage Design

- **Bucket-per-org isolation**: Each org gets a dedicated GCS bucket (`haderach-media-{org_slug}`)
- **Path structure**: `{org_slug}/{YYYY}/{MM}/{asset_id}/{filename}`
- **Signed URLs**: Upload and download via time-limited signed URLs (upload: 15min, download: 1hr)
- **CORS**: Configured for haderach.dev and localhost:5173

## API Contracts

Base path: `/media/api`

### Upload Flow

1. `POST /upload/initiate` — Returns signed upload URL + draft ID
2. Client PUTs file directly to GCS via signed URL
3. `POST /upload/finalize` — Confirms upload, runs auto-tag + embedding

### Asset CRUD

- `GET /assets` — List (paginated)
- `GET /assets/{id}` — Single asset with reference count
- `PATCH /assets/{id}` — Update editable fields
- `DELETE /assets/{id}` — Soft delete (warns if refs exist)

### Search

- `POST /search` — Combined text/semantic/hybrid search
- `GET /search/typeahead` — Fast prefix search

### References

- `GET /assets/{id}/references` — List references
- `POST /assets/{id}/references` — Register reference
- `DELETE /assets/{id}/references/{ref_id}` — Remove reference

### Delivery

- `GET /assets/{id}/url` — Signed download URL (1hr)

## Authentication

All endpoints require:
1. `Authorization: Bearer <firebase-id-token>`
2. `X-Active-Org: <slug>`

Local dev: Set `DEV_AUTH_EMAIL` to bypass Firebase verification.

## Search Implementation

### Full-text Search

Uses Postgres `tsvector` with weighted fields:
- A: title
- B: filename
- C: alt_text
- D: description

### Semantic Search

1. Query text → Vertex AI `text-embedding-005` (768 dimensions)
2. pgvector cosine distance search
3. Results combined with full-text via simple union (RRF planned for future)

## Auto-tagging

On upload finalize:
1. Call Vision API `label_detection` on GCS URI
2. Filter labels with confidence ≥ 0.7
3. Store as `source='auto'` tags

## CMS Integration Contract

The CMS Media field type (task 305) will:
1. Open a picker modal
2. Call `POST /search` or `GET /assets` for selection
3. On select, call `POST /assets/{id}/references` with `consumer_type='cms'`
4. Store the asset ID in the CMS content item
5. On delete, call `DELETE /assets/{id}/references/{ref_id}`

The asset ID is the stable reference. The CMS fetches display metadata and image URLs via the API.

## Deployment

- **Cloud Run**: `digital-media-api` service
- **Cloud SQL**: `haderach-digital-media` Postgres 15 with pgvector
- **GCS**: `haderach-media-{org}` buckets (Terraform-provisioned)
- **Secrets**: `DIGITAL_MEDIA_DATABASE_URL` in Secret Manager

## Related

- Task: [300 — Digital Media MVP](../../haderach-tasks/tasks/features/300-media-app.md)
- Strategy: [302 — Digital Asset Management](../../haderach-tasks/tasks/strategy/302-digital-asset-management/)
- CMS Integration: [305 — CMS Media Field Integration](../../haderach-tasks/tasks/features/305-cms-media-field-integration.md)
