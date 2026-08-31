"""Database seeding — idempotent, safe to run on every startup.

30 cameras map directly to the live Sentinel Grid (real HLS/RTSP/WHEP streams).
20 additional departmental cameras represent VMS nodes not yet on the Sentinel Grid.
"""
import logging
import random

from sqlalchemy.orm import Session

from app.models import Camera, Department, User, VehicleRecord, WatchlistEntry
from app.seed_data import DEPARTMENTAL_CAMERAS, SENTINEL_CAMERAS
from app.security import hash_password
from app.seed_watchlist import VAHAN_RECORDS, WATCHLIST

logger = logging.getLogger(__name__)

HLS_BASE  = "https://cctv.corp8.cloud"
RTSP_BASE = "rtsp://103.250.160.189:8554/stream"
WHEP_BASE = "http://103.250.160.189:8889/stream"


def seed(db: Session) -> None:
    # ── Departments ─────────────────────────────────────────────────────────
    if db.query(Department).count() == 0:
        depts = [
            Department(name="Ahmedabad City Police",   code="AHD",  description="Ahmedabad Commissionerate"),
            Department(name="Surat City Police",        code="SUR",  description="Surat Commissionerate"),
            Department(name="Vadodara City Police",     code="VAD",  description="Vadodara Commissionerate"),
            Department(name="Rajkot City Police",       code="RAJ",  description="Rajkot Commissionerate"),
            Department(name="Gujarat State Police HQ",  code="GSHP", description="State HQ / Traffic / Sentinel Grid"),
        ]
        db.add_all(depts)
        db.commit()
        logger.info("Seeded %d departments", len(depts))

    dept_by_code = {d.code: d.id for d in db.query(Department).all()}

    dept_for_city = {
        "Ahmedabad": "AHD", "Surat": "SUR", "Vadodara": "VAD",
        "Rajkot": "RAJ", "Gandhinagar": "GSHP",
    }

    # ── Cameras ──────────────────────────────────────────────────────────────
    if db.query(Camera).count() == 0:
        cameras = []

        # 30 real Sentinel Grid cameras
        sentinel_statuses = ["online"] * 27 + ["offline"] * 2 + ["maintenance"]
        for i, (sid, name, city, district, lat, lng, ctype, tier, road) in enumerate(SENTINEL_CAMERAS):
            status = sentinel_statuses[i % len(sentinel_statuses)]
            city_dept = dept_for_city.get(city)
            cameras.append(Camera(
                external_id=sid,
                department_id=dept_by_code[city_dept] if city_dept else dept_by_code["GSHP"],
                name=name,
                latitude=lat + random.uniform(-0.0002, 0.0002),
                longitude=lng + random.uniform(-0.0002, 0.0002),
                address=road,
                city=city,
                district=district,
                camera_type=ctype,
                codec="h265" if tier == "A" else "h264",
                resolution="1080p" if tier != "C" else "720p",
                fps=25 if tier == "A" else 15,
                has_ir=tier != "C",
                has_ptz=ctype == "ptz",
                # ── REAL Sentinel Grid stream URLs ──
                stream_url=f"{HLS_BASE}/{sid}/index.m3u8",
                rtsp_url=f"{RTSP_BASE}/{sid}",
                whep_url=f"{WHEP_BASE}/{sid}/whep",
                stream_protocol="hls",
                vms_vendor="Sentinel Grid",
                status=status,
                health_score=0.97 if status == "online" else (0.35 if status == "offline" else 0.70),
                analytics_tier=tier,
                analytics_config={
                    "fps_target": 5 if tier == "A" else 2,
                    "rtsp_transport": "tcp",  # §3 of integration.txt — always force TCP
                    "sentinel_id": sid,
                },
            ))

        # 20 departmental cameras (not on Sentinel Grid yet)
        dept_statuses = ["online"] * 16 + ["offline"] * 2 + ["maintenance"] * 2
        for i, (name, city, district, lat, lng, ctype, tier, road) in enumerate(DEPARTMENTAL_CAMERAS):
            status = dept_statuses[i % len(dept_statuses)]
            city_dept = dept_for_city.get(city)
            cameras.append(Camera(
                external_id=f"DEPT-{city[:3].upper()}-{2000 + i}",
                department_id=dept_by_code[city_dept] if city_dept else dept_by_code["GSHP"],
                name=name,
                latitude=lat + random.uniform(-0.0003, 0.0003),
                longitude=lng + random.uniform(-0.0003, 0.0003),
                address=road,
                city=city,
                district=district,
                camera_type=ctype,
                codec="h265" if tier == "A" else "h264",
                resolution="1080p" if tier != "C" else "720p",
                fps=25 if tier == "A" else 15,
                has_ir=tier != "C",
                has_ptz=False,
                stream_url=None,   # departmental — not yet on Sentinel Grid
                rtsp_url=None,
                whep_url=None,
                stream_protocol=None,
                vms_vendor="Departmental VMS",
                status=status,
                health_score=0.94 if status == "online" else (0.3 if status == "offline" else 0.65),
                analytics_tier=tier,
                analytics_config={"fps_target": 5 if tier == "A" else 2},
            ))

        db.add_all(cameras)
        db.commit()
        logger.info("Seeded %d cameras (%d Sentinel Grid + %d departmental)",
                    len(cameras), len(SENTINEL_CAMERAS), len(DEPARTMENTAL_CAMERAS))

    # ── Watchlist ─────────────────────────────────────────────────────────────
    if db.query(WatchlistEntry).count() == 0:
        for cat, stype, ident, sev, fir, ps, desc in WATCHLIST:
            db.add(WatchlistEntry(
                category=cat, subject_type=stype, identifier=ident,
                description=desc, severity=sev, fir_number=fir,
                police_station=ps, created_by="system-seed",
            ))
        db.commit()
        logger.info("Seeded %d watchlist entries", len(WATCHLIST))

    # ── Vehicle registry ──────────────────────────────────────────────────────
    if db.query(VehicleRecord).count() == 0:
        for rec in VAHAN_RECORDS:
            db.add(VehicleRecord(
                registration_number=rec[0], owner_name=rec[1], vehicle_class=rec[2],
                maker=rec[3], model=rec[4], color=rec[5], fuel_type=rec[6],
                registration_date=rec[7], insurance_valid_till=rec[8],
                fitness_valid_till=rec[9], rto_code=rec[10], rto_name=rec[11],
            ))
        db.commit()
        logger.info("Seeded %d vehicle records", len(VAHAN_RECORDS))

    # ── Users ─────────────────────────────────────────────────────────────────
    if db.query(User).count() == 0:
        users = [
            User(username="admin",    email="admin@gujivms.gov.in",    full_name="Control Room Admin",
                 hashed_password=hash_password("admin123"),    role="admin",    department="GSHP"),
            User(username="operator1",email="op1@gujivms.gov.in",      full_name="Operator One",
                 hashed_password=hash_password("operator123"), role="operator", department="AHD"),
            User(username="analyst1", email="an1@gujivms.gov.in",      full_name="Analyst One",
                 hashed_password=hash_password("analyst123"),  role="analyst",  department="AHD"),
        ]
        db.add_all(users)
        db.commit()
        logger.info("Seeded %d users", len(users))
