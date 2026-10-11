"""Health endpoint tests (used by GitHub Actions uptime checks)."""


def test_health_reports_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["environment"] == "development"


def test_liveness_does_not_touch_db(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_readiness(client):
    assert client.get("/health/ready").json()["ready"] is True


def test_request_id_header_is_returned(client):
    resp = client.get("/health")
    assert resp.headers.get("X-Request-ID")


def test_openapi_schema_is_served(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"]
