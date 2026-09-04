"""End-to-end API + correlation engine tests (plan §13 API contract).

Run: cd backend && python -m pytest tests/ -v
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.alert_engine import normalize_plate, fuzzy_plate_match


@pytest.fixture(scope="module")
def client():
    # `with` runs the lifespan (table creation + seeding, simulator disabled)
    with TestClient(app) as c:
        yield c


# ── Unit: plate normalization / fuzzy matching (plan §5 / §8.2) ──────────────

def test_normalize_plate():
    assert normalize_plate("gj 01 ab 1234") == "GJ01AB1234"
    assert normalize_plate("GJ-01-AB-1234") == "GJ01AB1234"


def test_fuzzy_plate_match_tolerates_ocr_errors():
    assert fuzzy_plate_match("GJ 01 AB 1234", "GJ01AB1234")
    assert fuzzy_plate_match("GJ01AB1234", "GJ0IAB1234")  # 1 <-> I OCR confusion
    assert not fuzzy_plate_match("GJ01AB1234", "GJ27XY9999")


# ── System ────────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Camera registry + GIS (plan §9 / §13) ────────────────────────────────────

def test_cameras_seeded_and_filters(client):
    r = client.get("/api/v1/cameras?limit=100")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 30
    assert len(body["items"]) == 30
    cam = body["items"][0]
    for key in ("id", "name", "latitude", "longitude", "status", "analytics_tier"):
        assert key in cam


def test_camera_stats_and_geo(client):
    assert client.get("/api/v1/cameras/stats").status_code == 200
    r = client.get("/api/v1/cameras/geo/nearby?lat=23.02&lng=72.57&radius_km=50")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    r = client.get("/api/v1/cameras/geo/coverage")
    assert r.status_code == 200 and len(r.json()) > 0
    r = client.get("/api/v1/cameras/gap-analysis")
    assert r.status_code == 200 and "districts" in r.json()


def test_camera_create_and_put_update(client):
    payload = {
        "name": "Test Junction Camera", "latitude": 23.03, "longitude": 72.58,
        "city": "Ahmedabad", "district": "Ahmedabad", "camera_type": "fixed",
    }
    r = client.post("/api/v1/cameras", json=payload)
    assert r.status_code == 201
    cam_id = r.json()["id"]

    r = client.put(f"/api/v1/cameras/{cam_id}", json={"name": "Renamed Camera"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Camera"

    assert client.delete(f"/api/v1/cameras/{cam_id}").status_code in (200, 204)


def test_camera_bulk_import(client):
    cams = [
        {"name": "Bulk Cam A", "latitude": 22.3, "longitude": 73.2,
         "city": "Vadodara", "district": "Vadodara"},
        {"name": "Bulk Cam B", "latitude": 21.1, "longitude": 72.8,
         "city": "Surat", "district": "Surat"},
    ]
    r = client.post("/api/v1/cameras/bulk", json=cams)
    assert r.status_code == 201


# ── Feeds (plan §10 / §13) ────────────────────────────────────────────────────

def test_feed_url_and_status(client):
    r = client.get("/api/v1/feeds/1/url")
    assert r.status_code == 200
    assert "hls" in r.json()
    r = client.get("/api/v1/feeds/status")
    assert r.status_code == 200 and r.json()["total"] >= 30


def test_feed_snapshot_graceful(client):
    """Snapshot returns a JPEG in prod (ffmpeg) or a clean 5xx locally — never a crash."""
    r = client.get("/api/v1/feeds/1/snapshot")
    assert r.status_code in (200, 502, 503, 504)
    assert client.get("/api/v1/feeds/99999/snapshot").status_code == 404


# ── Watchlist (plan §8 / §13) ─────────────────────────────────────────────────

def test_watchlist_crud(client):
    r = client.post("/api/v1/watchlist", json={
        "category": "stolen_vehicle", "subject_type": "vehicle",
        "identifier": "GJ 99 ZZ 0001", "severity": "critical",
        "fir_number": "FIR-TEST-001",
    })
    assert r.status_code == 201
    entry_id = r.json()["id"]
    assert client.patch(f"/api/v1/watchlist/{entry_id}",
                        json={"severity": "high"}).status_code == 200
    assert client.delete(f"/api/v1/watchlist/{entry_id}").status_code in (200, 204)


def test_watchlist_bulk_import_json(client):
    items = [
        {"identifier": "GJ 98 YY 1111", "category": "stolen_vehicle", "severity": "high"},
        {"identifier": "GJ 97 XX 2222", "category": "wanted_person",
         "subject_type": "person", "severity": "critical"},
        {"identifier": "GJ 01 AB 1234", "category": "stolen_vehicle"},  # seeded dup
    ]
    r = client.post("/api/v1/watchlist/bulk-import", json={"items": items})
    assert r.status_code == 201
    body = r.json()
    assert body["created"] == 2
    assert body["skipped"] == 1
    assert body["skipped_details"][0]["reason"] == "duplicate"


def test_watchlist_bulk_import_csv(client):
    csv_body = (
        "category,subject_type,identifier,severity\n"
        "stolen_vehicle,vehicle,GJ 96 WW 3333,high\n"
        "missing_person,person,GJ 95 VV 4444,critical\n"
    )
    r = client.post("/api/v1/watchlist/bulk-import",
                    content=csv_body, headers={"Content-Type": "text/csv"})
    assert r.status_code == 201
    assert r.json()["created"] == 2


# ── Federation ingest → alert engine → alert workflow (plan §3 / §8 / §13) ───

def test_ingest_anpr_watchlist_hit_and_alert_workflow(client):
    """Full pipeline: edge node ingests ANPR of a watchlisted plate →
    correlation engine raises alert → acknowledge → resolve."""
    plate = "GJ 01 AB 1234"  # seeded watchlist vehicle
    for cam_id in (1, 5):    # sightings at two cameras → journey data
        r = client.post("/api/v1/ingest/anpr", json={
            "camera_id": cam_id, "plate_text": plate, "confidence": 0.94,
            "vehicle_type": "car", "direction": "inbound",
        })
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "alert_created"

    # Alert queue contains the new hit
    r = client.get("/api/v1/alerts?status=new&limit=5")
    alert = next(a for a in r.json()["items"] if a["detected_identifier"] == plate)
    aid = alert["id"]

    r = client.put(f"/api/v1/alerts/{aid}/acknowledge")
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"

    r = client.put(f"/api/v1/alerts/{aid}/resolve")
    assert r.status_code == 200 and r.json()["status"] == "resolved"


def test_ingest_anpr_unknown_camera(client):
    r = client.post("/api/v1/ingest/anpr",
                    json={"camera_id": 99999, "plate_text": "GJ01AA0000"})
    assert r.status_code == 404


# ── Real face-recognition correlation (plan §6 — ArcFace gallery path) ───────

def test_face_enrollment_and_embedding_correlation(client):
    # 1. Create a person entry and enroll a reference ArcFace embedding
    r = client.post("/api/v1/watchlist", json={
        "category": "wanted_person", "subject_type": "person",
        "identifier": "Test Suspect (Real Face)", "severity": "critical",
    })
    assert r.status_code == 201
    entry_id = r.json()["id"]

    ref = [1.0] * 128  # ≥64-dim vector for the test (ArcFace is 512 in prod)
    r = client.post(f"/api/v1/watchlist/{entry_id}/enroll-face",
                    json={"embedding": ref})
    assert r.status_code == 200
    assert r.json()["status"] == "enrolled"
    assert r.json()["embedding_dim"] == 128

    # enrolled flag now shows in watchlist listing
    items = client.get("/api/v1/watchlist").json()["items"]
    enrolled = next(i for i in items if i["id"] == entry_id)
    assert enrolled["face_enrolled"] is True

    # 2. Edge node detects a face with a near-identical embedding → alert
    r = client.post("/api/v1/ingest/detection", json={
        "camera_id": 1, "event_type": "face", "confidence": 0.93,
        "bbox": {"x": 100, "y": 80, "w": 90, "h": 120},
        "metadata": {"embedding": ref, "face_name": "unknown face"},
    })
    assert r.status_code == 201
    body = r.json()
    assert body["correlation"] == "alert_created"
    assert body["alert_id"] is not None

    # 3. A face with an orthogonal/dissimilar embedding → no alert
    r = client.post("/api/v1/ingest/detection", json={
        "camera_id": 1, "event_type": "face", "confidence": 0.9,
        "metadata": {"embedding": [1.0] + [0.0] * 127, "face_name": "unknown face"},
    })
    assert r.json()["correlation"] == "no_match"

    # 4. Enrollment rejects vehicle entries
    r = client.post("/api/v1/watchlist", json={
        "category": "stolen_vehicle", "subject_type": "vehicle",
        "identifier": "GJ 55 NN 5555",
    })
    vid = r.json()["id"]
    assert client.post(f"/api/v1/watchlist/{vid}/enroll-face",
                       json={"embedding": ref}).status_code == 400

    # cleanup
    client.delete(f"/api/v1/watchlist/{entry_id}")
    client.delete(f"/api/v1/watchlist/{vid}")


# ── Vehicle search & journey reconstruction (plan §7 / §20.2) ────────────────

def test_vehicle_journey_reconstruction(client):
    plate = "GJ%2001%20AB%201234"
    r = client.get(f"/api/v1/vehicles/search/{plate}")
    assert r.status_code == 200
    body = r.json()
    assert body["sightings_count"] >= 2
    assert body["plate_normalized"] == "GJ01AB1234"
    assert body["registry"] and body["registry"]["registration_number"] == "GJ01AB1234"
    assert len(body["legs"]) == body["sightings_count"] - 1

    r = client.get(f"/api/v1/vehicles/last-seen/{plate}")
    assert r.status_code == 200 and r.json()["plate"] == "GJ 01 AB 1234"


# ── Analytics + reports (plan §13) ────────────────────────────────────────────

def test_analytics_endpoints(client):
    for path in ("/api/v1/analytics/overview", "/api/v1/analytics/anpr?limit=5",
                 "/api/v1/analytics/traffic", "/api/v1/analytics/tiers/coverage",
                 "/api/v1/vehicles/traffic/by-hour", "/api/v1/vehicles/traffic/by-camera"):
        assert client.get(path).status_code == 200, path


def test_csv_and_pdf_reports(client):
    r = client.get("/api/v1/reports/anpr.csv")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert r.text.splitlines()[0].startswith("id,plate")

    r = client.get("/api/v1/reports/alerts.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"

    for kind in ("anpr", "cameras"):
        r = client.get(f"/api/v1/reports/{kind}.pdf")
        assert r.status_code == 200 and r.content[:5] == b"%PDF-", kind


# ── Auth (plan §17) ───────────────────────────────────────────────────────────

def test_login_flow(client, monkeypatch):
    from app.config import settings

    r = client.post("/api/v1/auth/login",
                    data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert r.json()["user"]["role"] == "admin"

    # With auth enforced, a valid token resolves the real user…
    monkeypatch.setattr(settings, "REQUIRE_AUTH", True)
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["username"] == "admin"

    # …and a missing token is rejected with 401.
    assert client.get("/api/v1/auth/me").status_code == 401
    # Invalid token → 401
    bad = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


# ── RBAC + audit trail (plan §17.2 / §17.1 Layer 4) ──────────────────────────

def test_rbac_denies_unprivileged_role_and_allows_admin_with_audit_trail(client, monkeypatch):
    """When REQUIRE_AUTH is on: analyst (no CAMERA_MANAGE) is forbidden from
    deleting a camera, admin succeeds, and the deletion is attributed + logged
    to the audit trail retrievable via GET /system/audit."""
    from app.config import settings

    admin_token = client.post(
        "/api/v1/auth/login", data={"username": "admin", "password": "admin123"}
    ).json()["access_token"]
    analyst_token = client.post(
        "/api/v1/auth/login", data={"username": "analyst1", "password": "analyst123"}
    ).json()["access_token"]

    # Create the target camera while auth enforcement is still off.
    r = client.post("/api/v1/cameras", json={
        "name": "RBAC Test Camera", "latitude": 23.0, "longitude": 72.5,
        "city": "Ahmedabad", "district": "Ahmedabad",
    })
    assert r.status_code == 201
    cam_id = r.json()["id"]

    monkeypatch.setattr(settings, "REQUIRE_AUTH", True)

    # (a) analyst lacks CAMERA_MANAGE -> 403, camera untouched
    r = client.delete(f"/api/v1/cameras/{cam_id}",
                      headers={"Authorization": f"Bearer {analyst_token}"})
    assert r.status_code == 403
    assert client.get(f"/api/v1/cameras/{cam_id}",
                      headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200

    # (b) admin has CAMERA_MANAGE -> succeeds
    r = client.delete(f"/api/v1/cameras/{cam_id}",
                      headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code in (200, 204)

    # (c) audit entry recorded with real attribution, retrievable via the API
    r = client.get("/api/v1/system/audit?limit=20",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    hit = next(
        (e for e in r.json()["items"]
         if e["action"] == "camera.delete" and e["target_id"] == str(cam_id)),
        None,
    )
    assert hit is not None
    assert hit["actor"] == "admin"

    # audit endpoint is itself gated (SYSTEM_CONFIG, admin-only)
    assert client.get(
        "/api/v1/system/audit", headers={"Authorization": f"Bearer {analyst_token}"}
    ).status_code == 403
    # and rejects an out-of-range limit rather than allowing unbounded reads
    assert client.get(
        "/api/v1/system/audit?limit=99999",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).status_code == 422


def test_demo_mode_still_allows_mutation_without_token(client):
    """REQUIRE_AUTH is False by default on this fixture — permission checks
    and attribution must be a complete no-op, matching pre-RBAC behavior."""
    from app.config import settings
    assert settings.REQUIRE_AUTH is False

    r = client.post("/api/v1/cameras", json={
        "name": "Demo Mode Camera", "latitude": 23.1, "longitude": 72.6,
        "city": "Ahmedabad", "district": "Ahmedabad",
    })
    assert r.status_code == 201
    cam_id = r.json()["id"]
    assert client.delete(f"/api/v1/cameras/{cam_id}").status_code in (200, 204)

    # watchlist mutation attribution falls back to "control-room" in demo mode
    r = client.post("/api/v1/watchlist", json={
        "category": "stolen_vehicle", "subject_type": "vehicle",
        "identifier": "GJ 11 DM 0001", "severity": "high",
    })
    assert r.status_code == 201
    entry_id = r.json()["id"]
    client.delete(f"/api/v1/watchlist/{entry_id}")


# ── System (plan §11.2 / §13) ────────────────────────────────────────────────

def test_system_adapters_and_health(client):
    r = client.get("/api/v1/system/adapters")
    assert r.status_code == 200
    body = r.json()
    assert "sentinel" in body["registry"]        # connector registry (plan §11.2)
    assert "connected_vms_vendors" in body
    assert client.get("/api/v1/system/health").json()["status"] == "ok"


# ── Hardening: bounded limits + rate limiting (Render free-tier) ────────────

def test_report_and_vehicle_limits_are_capped(client):
    """A caller cannot force an unbounded export/scan by passing a huge
    `limit` — over-range values are rejected with 422 rather than silently
    trying to load millions of rows into a 512MB container."""
    # reports.py — CSV/PDF export limits
    assert client.get("/api/v1/reports/anpr.csv?limit=5000000").status_code == 422
    assert client.get("/api/v1/reports/anpr.pdf?limit=5000000").status_code == 422
    assert client.get("/api/v1/reports/anpr.csv?limit=5000").status_code == 200  # still within cap

    # vehicles.py
    assert client.get("/api/v1/vehicles?limit=999999").status_code == 422
    assert client.get("/api/v1/vehicles/recent?limit=999999").status_code == 422
    assert client.get("/api/v1/vehicles/traffic/by-camera?limit=999999").status_code == 422

    # analytics.py
    assert client.get("/api/v1/analytics/anpr?limit=999999").status_code == 422
    assert client.get("/api/v1/analytics/anpr/search?plate=GJ01&limit=999999").status_code == 422
    assert client.get("/api/v1/analytics/faces?limit=999999").status_code == 422
    assert client.get("/api/v1/analytics/events?limit=999999").status_code == 422


def test_rate_limiter_returns_429_when_tripped(client):
    """The in-process fixed-window limiter trips at a low threshold and
    recovers, without leaking state into other tests (reset() before/after)
    or throttling the exempt /health check."""
    from app.main import rate_limiter

    original_limit = rate_limiter.limit
    rate_limiter.reset()
    rate_limiter.limit = 3
    try:
        statuses = [client.get("/api/v1/analytics/overview").status_code for _ in range(6)]
        assert 429 in statuses
        tripped_response = client.get("/api/v1/analytics/overview")
        assert tripped_response.status_code == 429
        assert "Retry-After" in tripped_response.headers
        # /health must stay exempt even while the limiter is tripped
        assert client.get("/health").status_code == 200
    finally:
        rate_limiter.limit = original_limit
        rate_limiter.reset()

    # Limiter is back to normal — subsequent requests in the rest of the
    # suite are not throttled.
    assert client.get("/health").status_code == 200