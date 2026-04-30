"""Basic API tests for the Digital Media service."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    import os
    os.environ["DEV_AUTH_EMAIL"] = "test@example.com"
    os.environ["DATABASE_URL"] = ""
    
    from service.app import app
    return TestClient(app)


def test_health(client):
    """Health endpoint should return ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
