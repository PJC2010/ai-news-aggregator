from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_session
from app.main import app


def test_health_auth_and_static_route_order(factory, settings):
    def session_override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = session_override
    # require_operator reads the cached settings directly.
    original = get_settings().operator_api_key
    get_settings().operator_api_key = "test-key"
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/clusters").status_code == 401
            headers = {"X-Operator-Key": "test-key"}
            today = client.get("/clusters/today", headers=headers)
            assert today.status_code == 200 and today.json()["items"] == []
            assert client.get("/clusters?limit=101", headers=headers).status_code == 422
            assert client.get("/clusters?topic=%25", headers=headers).json()["total"] == 0
            assert (
                client.get(
                    "/clusters/00000000-0000-0000-0000-000000000001", headers=headers
                ).status_code
                == 404
            )
            get_settings().operator_api_key = ""
            assert client.get("/clusters", headers=headers).status_code == 503
    finally:
        get_settings().operator_api_key = original
        app.dependency_overrides.clear()
