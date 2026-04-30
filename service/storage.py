"""GCS signed URL helpers for upload and download."""

import logging
import mimetypes
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import google.auth
import google.auth.compute_engine
import google.auth.iam
import google.auth.transport.requests
from google.cloud import storage

from .config import get_settings

logger = logging.getLogger(__name__)

_client: storage.Client | None = None
_signing_credentials = None
_auth_request = None


def get_storage_client() -> storage.Client:
    """Get or create a GCS client."""
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def get_signing_credentials():
    """Get signing credentials for generating signed URLs in Cloud Run.
    
    Cloud Run uses compute engine credentials which don't have a private key.
    We wrap them with an IAM signer to use the signBlob API instead.
    """
    global _signing_credentials, _auth_request
    
    if _signing_credentials is None:
        credentials, project = google.auth.default()
        _auth_request = google.auth.transport.requests.Request()
        
        # Refresh credentials to ensure they're valid
        if not credentials.valid:
            credentials.refresh(_auth_request)
        
        # Get the service account email
        if hasattr(credentials, "service_account_email"):
            sa_email = credentials.service_account_email
        else:
            # Fetch from metadata server for compute engine credentials
            import requests as req
            resp = req.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
                headers={"Metadata-Flavor": "Google"},
                timeout=5,
            )
            sa_email = resp.text
        
        # Create an IAM signer that uses the signBlob API
        signer = google.auth.iam.Signer(
            _auth_request,
            credentials,
            sa_email,
        )
        
        # Create signing credentials with the IAM signer
        _signing_credentials = google.auth.compute_engine.Credentials(
            service_account_email=sa_email,
            signer=signer,
        )
    
    return _signing_credentials


def get_bucket_name(org_slug: str) -> str:
    """Return the bucket name for an org."""
    settings = get_settings()
    return f"{settings.gcs_bucket_prefix}-{org_slug}"


def generate_upload_path(org_slug: str, draft_id: UUID, filename: str) -> str:
    """Generate a storage path for a new upload."""
    now = datetime.utcnow()
    return f"{org_slug}/{now.year}/{now.month:02d}/{draft_id}/{filename}"


def generate_signed_upload_url(
    bucket_name: str,
    gcs_path: str,
    content_type: str,
    expiration_minutes: int = 15,
    draft_id: UUID | None = None,
) -> str:
    """Generate a URL for uploading a file. Uses local endpoint in dev mode."""
    settings = get_settings()
    
    if settings.local_storage_mode:
        return f"http://localhost:8000/upload/local/{draft_id}"
    
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)

    # In Cloud Run, use signing credentials with IAM signer
    signing_creds = get_signing_credentials()
    
    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expiration_minutes),
        method="PUT",
        content_type=content_type,
        credentials=signing_creds,
    )
    return url


def generate_signed_download_url(
    bucket_name: str,
    gcs_path: str,
    expiration_minutes: int = 60,
) -> str:
    """Generate a URL for downloading a file. Uses local endpoint in dev mode."""
    settings = get_settings()
    
    if settings.local_storage_mode:
        return f"http://localhost:8000/files/{gcs_path}"
    
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)

    # In Cloud Run, use signing credentials with IAM signer
    signing_creds = get_signing_credentials()
    
    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=expiration_minutes),
        method="GET",
        credentials=signing_creds,
    )
    return url


def get_local_file_path(gcs_path: str) -> Path:
    """Get the local file path for a given gcs_path."""
    settings = get_settings()
    return settings.get_local_storage_dir() / gcs_path


def save_local_file(gcs_path: str, content: bytes) -> None:
    """Save a file to local storage."""
    file_path = get_local_file_path(gcs_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    logger.info("Saved local file: %s", file_path)


def get_blob_metadata(bucket_name: str, gcs_path: str) -> dict | None:
    """Fetch blob metadata. Works with local files in dev mode."""
    settings = get_settings()
    
    if settings.local_storage_mode:
        file_path = get_local_file_path(gcs_path)
        if not file_path.exists():
            return None
        
        content_type, _ = mimetypes.guess_type(str(file_path))
        return {
            "size": file_path.stat().st_size,
            "content_type": content_type or "application/octet-stream",
            "md5_hash": None,
            "metadata": {},
        }
    
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)

    if not blob.exists():
        return None

    blob.reload()
    return {
        "size": blob.size,
        "content_type": blob.content_type,
        "md5_hash": blob.md5_hash,
        "metadata": blob.metadata or {},
    }


def delete_blob(bucket_name: str, gcs_path: str) -> bool:
    """Delete a blob. Works with local files in dev mode."""
    settings = get_settings()
    
    if settings.local_storage_mode:
        file_path = get_local_file_path(gcs_path)
        try:
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            logger.warning("Failed to delete local file %s: %s", file_path, e)
            return False
    
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)

    try:
        blob.delete()
        return True
    except Exception as e:
        logger.warning("Failed to delete blob %s/%s: %s", bucket_name, gcs_path, e)
        return False
