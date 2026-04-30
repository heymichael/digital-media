"""Firebase ID token verification for FastAPI endpoints."""

import logging
from urllib.request import urlopen

import firebase_admin
from firebase_admin import auth as firebase_auth
from fastapi import HTTPException, Request

from .config import get_settings

logger = logging.getLogger(__name__)

_FIREBASE_CERT_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)

_ACTIVE_ORG_HEADER = "X-Active-Org"

_firebase_initialized = False


def _ensure_firebase():
    """Initialize Firebase Admin SDK if not in dev mode and not already initialized."""
    global _firebase_initialized
    settings = get_settings()
    if not settings.dev_auth_email and not _firebase_initialized and not firebase_admin._apps:
        firebase_admin.initialize_app()
        _firebase_initialized = True


def warm_firebase_public_keys(timeout: float = 5.0) -> None:
    """Prime the network path Firebase token verification depends on."""
    settings = get_settings()
    if settings.dev_auth_email:
        return
    _ensure_firebase()
    with urlopen(_FIREBASE_CERT_URL, timeout=timeout) as response:
        response.read()


def get_verified_user(request: Request) -> dict:
    """FastAPI dependency that verifies a Firebase ID token.

    Reads the Authorization header, verifies the token with Firebase Admin SDK,
    and returns the decoded token dict (contains 'email', 'uid', etc.) augmented
    with `org_slug` from the X-Active-Org header.
    """
    settings = get_settings()
    org_slug = request.headers.get(_ACTIVE_ORG_HEADER)

    if settings.dev_auth_email:
        email = request.headers.get("X-Test-Email", settings.dev_auth_email)
        return {
            "email": email,
            "uid": "dev-local",
            "org_slug": org_slug or "haderach",
        }

    _ensure_firebase()
    
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )
    token = header.removeprefix("Bearer ")
    try:
        decoded = firebase_auth.verify_id_token(token)
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as exc:
        logger.warning("Token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Token verification failed")

    if not org_slug:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "Active-Org-Required",
                "message": "X-Active-Org header is required.",
            },
        )

    decoded["org_slug"] = org_slug
    return decoded
