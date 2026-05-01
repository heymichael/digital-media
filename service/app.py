"""FastAPI Digital Media service — asset management and search."""

import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .auth import get_verified_user, warm_firebase_public_keys
from .config import get_settings
from .embeddings import (
    build_embedding_text,
    get_embedding_sync,
    init_vertex_ai,
    MODEL_NAME,
)
from .models import (
    Asset,
    AssetUpdate,
    AssetWithRefs,
    DeleteResponse,
    Reference,
    ReferenceCreate,
    SearchRequest,
    UploadFinalizeRequest,
    UploadInitiateRequest,
    UploadInitiateResponse,
)
from .storage import (
    generate_signed_download_url,
    generate_signed_upload_url,
    generate_upload_path,
    get_blob_metadata,
    get_bucket_name,
    get_local_file_path,
    save_local_file,
)
from .tagging import auto_tag_image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        db.warm_connection_pool()
        logger.info("Postgres pool warmed")
    except Exception:
        logger.exception("Failed to warm Postgres pool at startup")

    try:
        warm_firebase_public_keys()
        logger.info("Firebase public keys warmed")
    except Exception:
        logger.exception("Failed to warm Firebase public keys at startup")

    try:
        init_vertex_ai()
        logger.info("Vertex AI initialized")
    except Exception:
        logger.exception("Failed to initialize Vertex AI at startup")

    try:
        yield
    finally:
        db.close_pool()


app = FastAPI(
    title="Digital Media Service",
    root_path="/media/api",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://haderach.dev", "http://localhost:5173", "http://localhost:5176"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


_pending_uploads: dict[str, str] = {}


@app.post("/upload/initiate", response_model=UploadInitiateResponse)
def initiate_upload(
    req: UploadInitiateRequest,
    caller: dict = Depends(get_verified_user),
):
    """Generate a signed URL for uploading a file to GCS."""
    org_slug = caller["org_slug"]
    draft_id = uuid4()
    bucket = get_bucket_name(org_slug)
    gcs_path = generate_upload_path(org_slug, draft_id, req.filename)
    upload_url = generate_signed_upload_url(bucket, gcs_path, req.content_type, draft_id=draft_id)

    _pending_uploads[str(draft_id)] = gcs_path

    return UploadInitiateResponse(
        draft_id=draft_id,
        upload_url=upload_url,
        gcs_path=gcs_path,
    )


@app.put("/upload/local/{draft_id}")
async def upload_local(draft_id: str, request: Request):
    """Accept file upload for local development mode."""
    if draft_id not in _pending_uploads:
        raise HTTPException(status_code=404, detail="Unknown draft ID")

    gcs_path = _pending_uploads[draft_id]
    content = await request.body()
    save_local_file(gcs_path, content)

    return {"status": "ok", "gcs_path": gcs_path}


@app.get("/files/{path:path}")
def serve_local_file(path: str):
    """Serve files from local storage for development mode."""
    from fastapi.responses import FileResponse

    file_path = get_local_file_path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)


@app.post("/upload/finalize", response_model=Asset)
def finalize_upload(
    req: UploadFinalizeRequest,
    caller: dict = Depends(get_verified_user),
):
    """Confirm upload, run auto-tagging and embedding, return asset."""
    org_slug = caller["org_slug"]
    email = caller.get("email", "unknown")
    bucket = get_bucket_name(org_slug)

    meta = get_blob_metadata(bucket, req.gcs_path)
    if not meta:
        raise HTTPException(
            status_code=400,
            detail="Upload not found in storage. Ensure the file was uploaded.",
        )

    filename = req.gcs_path.split("/")[-1]
    content_type = meta.get("content_type", "application/octet-stream")
    size_bytes = meta.get("size", 0)

    asset = db.create_asset(
        org_slug=org_slug,
        gcs_bucket=bucket,
        gcs_path=req.gcs_path,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        width=None,
        height=None,
        uploaded_by=email,
    )

    asset_id = UUID(str(asset["id"]))
    gcs_uri = f"gs://{bucket}/{req.gcs_path}"

    settings = get_settings()

    if not settings.local_storage_mode:
        try:
            tags = auto_tag_image(gcs_uri)
            db.add_asset_tags(asset_id, tags)
            logger.info("Added %d auto-tags to asset %s", len(tags), asset_id)
        except Exception:
            logger.exception("Auto-tagging failed for asset %s", asset_id)

        try:
            text = build_embedding_text(asset)
            if text.strip():
                embedding = get_embedding_sync(text)
                db.store_embedding(asset_id, embedding, MODEL_NAME)
                logger.info("Stored embedding for asset %s", asset_id)
        except Exception:
            logger.exception("Embedding generation failed for asset %s", asset_id)
    else:
        logger.info("Skipping auto-tagging and embeddings in local storage mode")

    return Asset(**asset)


@app.get("/assets", response_model=list[Asset])
def list_assets(
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    caller: dict = Depends(get_verified_user),
):
    """List assets for the caller's org."""
    org_slug = caller["org_slug"]
    assets = db.list_assets(org_slug, limit=limit, offset=offset)
    return [Asset(**a) for a in assets]


@app.get("/assets/{asset_id}", response_model=AssetWithRefs)
def get_asset(
    asset_id: UUID,
    caller: dict = Depends(get_verified_user),
):
    """Get a single asset with reference count."""
    org_slug = caller["org_slug"]
    asset = db.get_asset(asset_id, org_slug)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    ref_count = db.count_asset_references(asset_id)
    return AssetWithRefs(**asset, reference_count=ref_count)


@app.patch("/assets/{asset_id}", response_model=Asset)
def update_asset(
    asset_id: UUID,
    updates: AssetUpdate,
    caller: dict = Depends(get_verified_user),
):
    """Update editable metadata fields on an asset."""
    org_slug = caller["org_slug"]
    update_dict = updates.model_dump(exclude_unset=True)

    asset = db.update_asset(asset_id, org_slug, **update_dict)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return Asset(**asset)


@app.delete("/assets/{asset_id}", response_model=DeleteResponse)
def delete_asset(
    asset_id: UUID,
    force: bool = Query(False),
    caller: dict = Depends(get_verified_user),
):
    """Soft delete an asset. Warns if references exist unless force=True."""
    org_slug = caller["org_slug"]

    asset = db.get_asset(asset_id, org_slug)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    ref_count = db.count_asset_references(asset_id)

    if ref_count > 0 and not force:
        refs = db.list_asset_references(asset_id)
        return DeleteResponse(
            deleted=False,
            warning=True,
            ref_count=ref_count,
            refs=[Reference(**r) for r in refs],
        )

    db.soft_delete_asset(asset_id, org_slug)
    return DeleteResponse(deleted=True)


@app.get("/assets/{asset_id}/url")
def get_asset_url(
    asset_id: UUID,
    caller: dict = Depends(get_verified_user),
):
    """Get a signed download URL for an asset."""
    org_slug = caller["org_slug"]
    asset = db.get_asset(asset_id, org_slug)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    url = generate_signed_download_url(asset["gcs_bucket"], asset["gcs_path"])
    return {"url": url, "expires_in": 3600}


@app.post("/search", response_model=list[Asset])
def search_assets(
    req: SearchRequest,
    caller: dict = Depends(get_verified_user),
):
    """Search assets using text, semantic, or hybrid search."""
    org_slug = caller["org_slug"]
    results = []

    if req.mode in ("text", "hybrid"):
        text_results = db.search_assets_fulltext(org_slug, req.query, limit=req.limit)
        results.extend(text_results)

    if req.mode in ("semantic", "hybrid"):
        try:
            query_embedding = get_embedding_sync(req.query)
            semantic_results = db.search_assets_semantic(
                org_slug, query_embedding, limit=req.limit
            )
            for r in semantic_results:
                if r["id"] not in [x["id"] for x in results]:
                    results.append(r)
        except Exception:
            logger.exception("Semantic search failed")

    return [Asset(**r) for r in results[:req.limit]]


@app.get("/search/typeahead", response_model=list[Asset])
def typeahead_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, le=50),
    caller: dict = Depends(get_verified_user),
):
    """Fast prefix search for autocomplete."""
    org_slug = caller["org_slug"]
    results = db.search_assets_fulltext(org_slug, q, limit=limit)
    return [Asset(**r) for r in results]


@app.get("/assets/{asset_id}/references", response_model=list[Reference])
def list_references(
    asset_id: UUID,
    caller: dict = Depends(get_verified_user),
):
    """List all references to an asset."""
    org_slug = caller["org_slug"]
    asset = db.get_asset(asset_id, org_slug)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    refs = db.list_asset_references(asset_id)
    return [Reference(**r) for r in refs]


@app.post("/assets/{asset_id}/references", response_model=Reference, status_code=201)
def create_reference(
    asset_id: UUID,
    req: ReferenceCreate,
    caller: dict = Depends(get_verified_user),
):
    """Register a reference to an asset."""
    org_slug = caller["org_slug"]
    asset = db.get_asset(asset_id, org_slug)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    ref = db.create_reference(
        asset_id=asset_id,
        consumer_type=req.consumer_type,
        consumer_id=req.consumer_id,
        consumer_field=req.consumer_field,
        org_slug=org_slug,
    )
    return Reference(**ref)


@app.delete("/assets/{asset_id}/references/{ref_id}")
def delete_reference(
    asset_id: UUID,
    ref_id: UUID,
    caller: dict = Depends(get_verified_user),
):
    """Remove a reference."""
    org_slug = caller["org_slug"]
    asset = db.get_asset(asset_id, org_slug)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if not db.delete_reference(ref_id):
        raise HTTPException(status_code=404, detail="Reference not found")

    return {"deleted": True}
