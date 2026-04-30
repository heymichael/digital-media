"""Vertex AI embedding client for semantic search."""

import logging

from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingModel

from .config import get_settings

logger = logging.getLogger(__name__)

MODEL_NAME = "text-embedding-005"
DIMENSION = 768

_model: TextEmbeddingModel | None = None


def init_vertex_ai() -> None:
    """Initialize Vertex AI SDK."""
    settings = get_settings()
    aiplatform.init(
        project=settings.vertex_project,
        location=settings.vertex_location,
    )


def get_embedding_model() -> TextEmbeddingModel:
    """Get or create the embedding model instance."""
    global _model
    if _model is None:
        _model = TextEmbeddingModel.from_pretrained(MODEL_NAME)
    return _model


async def get_embedding(text: str) -> list[float]:
    """Generate embedding for text using Vertex AI."""
    model = get_embedding_model()
    embeddings = model.get_embeddings([text])
    return embeddings[0].values


def get_embedding_sync(text: str) -> list[float]:
    """Synchronous version of get_embedding."""
    model = get_embedding_model()
    embeddings = model.get_embeddings([text])
    return embeddings[0].values


def build_embedding_text(asset: dict) -> str:
    """Combine asset metadata into text for embedding."""
    parts = [
        asset.get("title", ""),
        asset.get("alt_text", ""),
        asset.get("description", ""),
        asset.get("filename", ""),
    ]
    return " ".join(filter(None, parts))
