"""Database seeding — idempotent, safe to run on every startup."""
import logging
import random

from sqlalchemy.orm import Session

from app.models import Camera, Department, User, VehicleRecord, WatchlistEntry
from app.seed_data import CAMERA_DEFS
from app.security import hash_password
from app.seed_watchlist import VAHAN_RECORDS, WATCHLIST

logger = logging.getLogger(__name__)


def seed(db: Session) -> None:
    if db.query(Department).count() == 0:
        depts = [
            Department(name="Ahmedabad City Police", code="AHD", description="Ahmedabad Commissionerate"),
            Department(name="Surat City Police", code="SUR", description="Surat Commissionerate"),
            Department(name="Vadodara City Police", code="VAD", description="Vadodara Commissionerate"),
            Department(name="Rajkot City Police", code="RAJ", description="Rajkot Commissionerate"),
            Department(name="Gujarat State Police HQ", code="GSHP", description="State Headquarters / Traffic"),
        ]
        db.add_all(depts)
        db.commit()
        logger.info("Seeded %d departments", len(depts))
    dept_by_code = {d.code: d.id for d in db.query(Department).all()}

    if db.query(Camera).count() == 0:
        dept_for_city = {
            "Ahmedabad": "AHD", "Surat": "SUR", "Vadodara": "VAD",
            "Rajkot": "RAJ", "Gandhinagar": "GSHP",
        }
        statuses = ["online"] * 44 + ["offline"] * 3 + ["maintenance"] * 2 + ["unknown"]
        cameras = []
        for i, (name, city, district, lat, lng, ctype, tier, road) in enumerate(CAMERA_DEFS):
            status = statuses[i % len(statuses)]
            city_dept = dept_for_city.get(city)
            cameras.append(
                Camera(
                    external_id=f"SNT-{city[:3].upper()}-{1000 + i}",
                    department_id=dept_by_code[city_dept] if city_dept else dept_by_code["GSHP"],
                    name=f"{name} ({city})",
                    latitude=lat + random.uniform(-0.0004, 0.0004),
                    longitude=lng + random.uniform(-0.0004, 0.0004),
                    address=road,
                    city=city,
                    district=district,
                    camera_type=ctype,
                    codec="h265" if tier == "A" else "h264",
                    resolution="1080p" if tier != "C" else "720p",
                    fps=25 if tier == "A" else 15,
                    has_ir=tier != "C",
                    has_ptz=ctype == "ptz",
                    stream_url=f"rtsp://sentinel.gujarat.gov.in:8554/live/cam{1000 + i}",
                    stream_protocol="rtsp",
                    vms_vendor="Sentinel Grid" if i % 3 else "Departmental VMS",
                    status=status,
                    health_score=0.97 if status == "online" else (0.4 if status == "offline" else 0.7),
                    analytics_tier=tier,
                    analytics_config={"fps_target": 5 if tier == "A" else 2},
                )
            )
        db.add_all(cameras)
        db.commit()
        logger.info("Seeded %d cameras", len(cameras))

    if db.query(WatchlistEntry).count() == 0:
        for cat, stype, ident, sev, fir, ps, desc in WATCHLIST:
            db.add(
                WatchlistEntry(
                    category=cat,
                    subject_type=stype,
                    identifier=ident,
                    description=desc,
                    severity=sev,
                    fir_number=fir,
                    police_station=ps,
                    created_by="system-seed",
                )
            )
        db.commit()
        logger.info("Seeded %d watchlist entries", len(WATCHLIST))

    if db.query(VehicleRecord).count() == 0:
        for rec in VAHAN_RECORDS:
            db.add(
                VehicleRecord(
                    registration_number=rec[0], owner_name=rec[1], vehicle_class=rec[2],
                    maker=rec[3], model=rec[4], color=rec[5], fuel_type=rec[6],
                    registration_date=rec[7], insurance_valid_till=rec[8],
                    fitness_valid_till=rec[9], rto_code=rec[10], rto_name=rec[11],
                )
            )
        db.commit()
        logger.info("Seeded %d vehicle records", len(VAHAN_RECORDS))

    if db.query(User).count() == 0:
        users = [
            User(username="admin", email="admin@gujivms.gov.in", full_name="Control Room Admin",
                 hashed_password=hash_password("admin123"), role="admin", department="GSHP"),
            User(username="operator1", email="op1@gujivms.gov.in", full_name="Operator One",
                 hashed_password=hash_password("operator123"), role="operator", department="AHD"),
            User(username="analyst1", email="an1@gujivms.gov.in", full_name="Analyst One",
                 hashed_password=hash_password("analyst123"), role="analyst", department="AHD"),
        ]
        db.add_all(users)
        db.commit()
        logger.info("Seeded %d users", len(users))
