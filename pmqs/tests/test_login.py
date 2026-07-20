from fastapi.testclient import TestClient
from pmqs.api.app import app


def test_login_is_public_and_has_google_action():
    response = TestClient(app).get("/login")
    assert response.status_code == 200
    assert "PMQs" in response.text
    assert "Make better product decisions." in response.text
    assert 'href="/auth/google/login"' in response.text
    assert "Continue with Google" in response.text


def test_login_has_no_authenticated_navigation():
    body = TestClient(app).get("/login").text
    assert 'class="rail"' not in body
    assert "product-switcher" not in body
    assert "Inbox" not in body
    assert "Workspace" not in body
