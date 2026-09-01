# Security Architecture — Gujarat IVMS

Implementation of plan §17 (Cybersecurity Architecture).

## 1. Authentication

- **JWT (HS256)** bearer tokens via `POST /api/v1/auth/login` (OAuth2 password form).
- Token claims: `sub` (username), `uid`, `role`, `iat`, `exp`
  (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 720).
- Passwords hashed with **PBKDF2-SHA256, 390,000 iterations** + per-user 16-byte
  random salt (stdlib `hashlib` — no native dependencies).
- `REQUIRE_AUTH=true` (recommended for production deployments) enforces
  `Authorization: Bearer` on all `/api/v1` business endpoints. Demo mode
  (`REQUIRE_AUTH=false`) disables enforcement and auto-authenticates a viewer
  session — intended only for the public hackathon deployment.

## 2. Authorization (RBAC)

- Roles: `admin`, `operator`, `analyst`, `viewer` (plan §17.2 permission matrix).
- `require_roles(*roles)` dependency factory restricts endpoints by role.
- User management (`/users`) is reserved for admins; disabling a user
  immediately invalidates their token resolution.

## 3. Federation ingest security (Model 3)

- Edge/regional nodes authenticate with the `X-API-Key` header, compared to the
  `INGEST_API_KEY` secret (constant set on Render, never committed).
- Ingest is metadata-only (plate text, confidence, bbox) — **no raw video ever
  reaches the central platform** (plan §1 guiding principle).

## 4. Transport & stream security

- Backend behind Render TLS (`https://…`); frontend served by Vercel TLS.
- Sentinel CDN credentials (`SENTINEL_PASSWORD`) live only in the backend
  environment; the HLS proxy re-authenticates server-side hourly and rewrites
  AES-128 playlist keys so browser clients never see CDN credentials.
- `SENTINEL_PASSWORD`, `SECRET_KEY`, `INGEST_API_KEY` are marked
  `sync: false` / `generateValue: true` in `render.yaml` — secrets are set in
  the Render dashboard, never in git.

## 5. CORS & browser surface

- `CORS_ORIGINS` allowlist (exact origins — currently the Vercel app domain and
  the Sentinel operator console). No wildcard in production.
- HLS proxy responses pin `Access-Control-Allow-Origin` to the allowed origins;
  segments get short-lived cache headers.

## 6. Data protection

- Only structured metadata is stored centrally: plate text, confidences,
  bounding boxes, event types. No continuous video archive is kept
  (plan §4 metadata-first architecture).
- Snapshot JPEGs are captured live and cached ≤ 8 s in memory; nothing is
  written to disk.
- SQLite/Postgres access uses SQLAlchemy parameter binding (no string SQL);
  ORM models validate all writes.

## 7. Audit trail

- Alert lifecycle is auditable: `status`, `acknowledged_by`, `acknowledged_at`,
  `resolved_at` on every alert; watchlist entries record `created_by`
  (`system-seed`, `bulk-import`, `control-room`).
- Camera health samples are persisted as a time-series log
  (`camera_health_log`) for forensic review.

## 8. Hardening checklist (deployment)

- [x] `SECRET_KEY` generated per-deployment (`generateValue: true` in render.yaml)
- [x] `REQUIRE_AUTH=true` recommended once demo/judging is complete
- [x] `INGEST_API_KEY` set before real edge nodes connect
- [x] CORS restricted to known frontend origins
- [x] Secrets excluded from git (`.gitignore`, `sync: false`)
- [x] Free-tier Postgres TLS enforced by Render managed DB
- [ ] Rotate `SECRET_KEY` quarterly (invalidates all sessions)
- [ ] Rate limiting at the edge/CDN for public demo deployments
