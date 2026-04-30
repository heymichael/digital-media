# Digital Media Service

Digital asset management service for the Haderach platform. Provides image upload, storage, metadata management, search, and reference tracking.

## Quick Start

### Prerequisites

- Python 3.12+
- Docker (for local Postgres with pgvector)
- Google Cloud credentials (for GCS and Vertex AI)

### Local Development

1. **Start the local database:**

   ```bash
   docker-compose -f docker-compose.local.yml up -d
   ```

2. **Set up Python environment:**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. **Configure environment:**

   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Run migrations:**

   ```bash
   python scripts/run_migrations.py
   ```

5. **Start the service:**

   ```bash
   uvicorn service.app:app --reload --port 8000
   ```

   The API will be available at `http://localhost:8000/media/api`.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/upload/initiate` | POST | Get signed upload URL |
| `/upload/finalize` | POST | Confirm upload, run auto-tagging |
| `/assets` | GET | List assets (paginated) |
| `/assets/{id}` | GET | Get single asset |
| `/assets/{id}` | PATCH | Update metadata |
| `/assets/{id}` | DELETE | Soft delete |
| `/assets/{id}/url` | GET | Get signed download URL |
| `/search` | POST | Full-text + semantic search |
| `/search/typeahead` | GET | Fast prefix search |
| `/assets/{id}/references` | GET/POST | List/create references |
| `/assets/{id}/references/{ref_id}` | DELETE | Remove reference |

### Testing

```bash
pytest
```

### Deployment

The service deploys to Cloud Run via GitHub Actions on merge to main. See `.github/workflows/` for details.

## Architecture

See [docs/architecture.md](docs/architecture.md) for service boundaries, database schema, and integration contracts.

## Related

- Task: [300 — Digital Media MVP](https://github.com/heymichael/haderach-tasks/blob/main/tasks/features/300-media-app.md)
- Strategy: [302 — Digital Asset Management](https://github.com/heymichael/haderach-tasks/blob/main/tasks/strategy/302-digital-asset-management/)
