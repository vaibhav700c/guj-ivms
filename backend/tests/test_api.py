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


# ── System (plan §11.2 / §13) ────────────────────────────────────────────────

def test_system_adapters_and_health(client):
    r = client.get("/api/v1/system/adapters")
    assert r.status_code == 200
    body = r.json()
    assert "sentinel" in body["registry"]        # connector registry (plan §11.2)
    assert "connected_vms_vendors" in body
    assert client.get("/api/v1/system/health").json()["status"] == "ok"