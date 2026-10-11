"""The CEO dashboard must actually be served, and must stay a static asset."""


def test_dashboard_index_is_served(client):
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    assert "CEO Dashboard" in resp.text
    assert "MassageVIP" in resp.text


def test_dashboard_assets_are_served(client):
    css = client.get("/dashboard/styles.css")
    assert css.status_code == 200
    assert "--accent" in css.text

    js = client.get("/dashboard/app.js")
    assert js.status_code == 200
    assert "/api/analytics/summary" in js.text


def test_dashboard_never_contains_a_supabase_key(client):
    """Guard-rail: no service-role key or Supabase URL may ship to the browser."""
    for path in ("/dashboard/", "/dashboard/app.js"):
        text = client.get(path).text.lower()
        assert "service_role" not in text
        assert "supabase.co" not in text
        assert "service-role" not in text


def test_dashboard_uses_textcontent_not_innerhtml_for_data(client):
    """XSS guard-rail: CRM values must not be injected as HTML."""
    js = client.get("/dashboard/app.js").text
    assert ".innerHTML" not in js
