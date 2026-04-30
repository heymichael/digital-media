"""Pydantic schemas for request/response models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AssetBase(BaseModel):
    title: str | None = None
    alt_text: str | None = None
    description: str | None = None
    approved_public: bool = False


class AssetCreate(AssetBase):
    pass


class AssetUpdate(AssetBase):
    pass


class Asset(AssetBase):
    id: UUID
    org_slug: str
    gcs_bucket: str
    gcs_path: str
    filename: str
    content_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    uploaded_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssetWithRefs(Asset):
    reference_count: int = 0


class UploadInitiateRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class UploadInitiateResponse(BaseModel):
    draft_id: UUID
    upload_url: str
    gcs_path: str


class UploadFinalizeRequest(BaseModel):
    draft_id: UUID
    gcs_path: str


class ReferenceCreate(BaseModel):
    consumer_type: str
    consumer_id: str
    consumer_field: str | None = None


class Reference(BaseModel):
    id: UUID
    asset_id: UUID
    consumer_type: str
    consumer_id: str
    consumer_field: str | None
    org_slug: str
    created_at: datetime

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    query: str
    mode: str = Field(default="hybrid", pattern="^(text|semantic|hybrid)$")
    limit: int = Field(default=20, le=100)


class Tag(BaseModel):
    tag: str
    source: str
    confidence: float | None = None


class DeleteResponse(BaseModel):
    deleted: bool
    warning: bool = False
    ref_count: int = 0
    refs: list[Reference] = []
