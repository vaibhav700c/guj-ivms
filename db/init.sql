-- Optional PostGIS/Timescale extensions for the full local stack.
-- The application schema is created by SQLAlchemy at startup (portable types).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;
