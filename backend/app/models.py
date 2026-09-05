"""SQLAlchemy ORM models — Gujarat IVMS data layer.

PostGIS is used in the full docker-compose stack; latitude/longitude columns
keep the schema portable across managed Postgres (Render) and SQLite (dev).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact: Mapped[dict] = mapped_column(JSON, default=dict)

    cameras: Mapped[list["Camera"]] = relationship(back_populates="department")


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(100), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True)
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    state: Mapped[str] = mapped_column(String(50), default="Gujarat")

    camera_type: Mapped[str | None] = mapped_column(String(50))
    codec: Mapped[str | None] = mapped_column(String(20))
    resolution: Mapped[str | None] = mapped_column(String(20))
    fps: Mapped[int | None] = mapped_column(Integer)
    has_ir: Mapped[bool] = mapped_column(Boolean, default=False)
    has_ptz: Mapped[bool] = mapped_column(Boolean, default=False)

    stream_url: Mapped[str | None] = mapped_column(String(500), nullable=True)   # HLS (CDN)
    rtsp_url: Mapped[str | None] = mapped_column(String(500), nullable=True)     # RTSP direct (AI inference)
    whep_url: Mapped[str | None] = mapped_column(String(500), nullable=True)     # WebRTC/WHEP (low-latency browser)
    stream_protocol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vms_vendor: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    analytics_tier: Mapped[str] = mapped_column(String(1), default="C")
    analytics_config: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    department: Mapped["Department | None"] = relationship(back_populates="cameras")


class VehicleRecord(Base):
    """VAHAN-like registry record (simulated govt integration)."""

    __tablename__ = "vehicle_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    vehicle_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    maker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registration_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    insurance_valid_till: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fitness_valid_till: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rto_code: Mapped[str | None] = mapped_column(String(10), index=True)
    rto_name: Mapped[str | None] = mapped_column(String(100), nullable=True)


class WatchlistEntry(Base):
    """Watchlist entry — stolen/blacklisted vehicles, wanted/missing persons."""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    subject_type: Mapped[str] = mapped_column(String(30), default="vehicle")
    identifier: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="high")
    fir_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    police_station: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Real face-recognition gallery (plan §6): 512-d ArcFace embedding enrolled
    # via POST /watchlist/{id}/enroll-face or the edge worker `enroll` command.
    reference_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)


class ANPREvent(Base):
    """ANPR detection event — edge/regional node → central platform."""

    __tablename__ = "anpr_events"
    __table_args__ = (
        Index("ix_anpr_plate_ts", "plate_text", "timestamp"),
        Index("ix_anpr_camera_ts", "camera_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    plate_text: Mapped[str] = mapped_column(String(20), index=True)
    plate_normalized: Mapped[str] = mapped_column(String(20), index=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vehicle_color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lane: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    embedding: Mapped[dict] = mapped_column(JSON, default=dict)
    # Real detection-frame evidence (base64 JPEG) captured by the edge worker
    # at the moment of this specific event — distinct from snapshot_ref, which
    # is a filesystem path only meaningful on the worker's own machine.
    evidence_image_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance: "edge_worker" for genuine detections ingested via the
    # federation API, "simulator" for events fabricated by the in-process
    # demo generator (app/simulator.py). Never trust a plate/detection is
    # real without checking this — see CLAUDE.md "Two event sources".
    source: Mapped[str] = mapped_column(String(20), default="edge_worker", index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    camera: Mapped["Camera"] = relationship()


class DetectionEvent(Base):
    """Generic object-detection / tracking event (person, vehicle, crowd)."""

    __tablename__ = "detection_events"
    __table_args__ = (Index("ix_det_camera_ts", "camera_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    track_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    bbox: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # Provenance — see ANPREvent.source above.
    source: Mapped[str] = mapped_column(String(20), default="edge_worker", index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id"), nullable=True)
    watchlist_id: Mapped[int | None] = mapped_column(ForeignKey("watchlist.id"), nullable=True)
    detected_identifier: Mapped[str | None] = mapped_column(String(200), index=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Real detection-frame evidence (base64 JPEG), captured by the edge worker
    # at match time and carried through from the ingest payload/source event —
    # renders directly in the UI without needing the worker's machine reachable.
    evidence_image_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance: inherited from the triggering event — "edge_worker" for a
    # genuine watchlist hit, "simulator" for one raised off fabricated demo
    # data. See ANPREvent.source above.
    source: Mapped[str] = mapped_column(String(20), default="edge_worker", index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    camera: Mapped["Camera | None"] = relationship()
    watchlist: Mapped["WatchlistEntry | None"] = relationship()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(30), default="operator")
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Audit & compliance trail (plan §17.1 Layer 4) — who did what, to what, when."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(100), default="anonymous")
    actor_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CameraHealthLog(Base):
    """Time-series camera health samples (plan §9.1 camera_health_log)."""

    __tablename__ = "camera_health_log"
    __table_args__ = (Index("ix_chl_camera_time", "camera_id", "time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    fps_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    packet_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance — see ANPREvent.source above. The simulator invents FPS/
    # latency/packet-loss numbers wholesale; a real health pipeline does not
    # exist yet, so every row is currently "simulator" until one is wired up.
    source: Mapped[str] = mapped_column(String(20), default="edge_worker", index=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
