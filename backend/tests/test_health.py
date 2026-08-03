"""Health endpoint contract tests."""

from fastapi.testclient import TestClient

from app.main import app


def _assert_healthy_response(path: str) -> None:
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {
        "service": app.state.settings.service_name,
        "status": "ok",
        "version": app.state.settings.app_version,
        "environment": app.state.settings.app_env,
    }


def test_root_health_endpoint() -> None:
    _assert_healthy_response("/health")


def test_versioned_health_endpoint() -> None:
    _assert_healthy_response("/api/v1/health")


def test_health_endpoint_allows_configured_frontend_origin() -> None:
    configured_origin = app.state.settings.cors_origins[0]

    with TestClient(app) as client:
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": configured_origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == configured_origin
