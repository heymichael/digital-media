"""Auto-tagging service using Vision API."""

import logging

from google.cloud import vision

logger = logging.getLogger(__name__)

_client: vision.ImageAnnotatorClient | None = None


def get_vision_client() -> vision.ImageAnnotatorClient:
    """Get or create the Vision API client."""
    global _client
    if _client is None:
        _client = vision.ImageAnnotatorClient()
    return _client


def auto_tag_image(gcs_uri: str, max_results: int = 10, min_confidence: float = 0.7) -> list[dict]:
    """Extract labels from an image using Vision API.
    
    Returns a list of dicts with 'tag', 'source', and 'confidence' keys.
    """
    client = get_vision_client()

    image = vision.Image(source=vision.ImageSource(gcs_image_uri=gcs_uri))
    response = client.label_detection(image=image, max_results=max_results)

    if response.error.message:
        logger.warning("Vision API error: %s", response.error.message)
        return []

    return [
        {
            "tag": label.description.lower(),
            "source": "auto",
            "confidence": label.score,
        }
        for label in response.label_annotations
        if label.score >= min_confidence
    ]
