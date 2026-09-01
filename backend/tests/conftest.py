"""Pytest configuration — isolated SQLite DB per test run.

Env vars must be set BEFORE app.config is imported anywhere.
"""
import os
import sys
import tempfile

# Make `app` importable when running from backend/tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fd, _db_path = tempfile.mkstemp(suffix=".ivms-test.db")
os.close(_fd)

os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SIMULATOR_AUTO_START"] = "false"   # deterministic tests — no background ticks
os.environ["SEED_ON_STARTUP"] = "true"         # 30 cameras, watchlist, VAHAN, users
os.environ["REQUIRE_AUTH"] = "false"           # demo mode like production
os.environ["INGEST_API_KEY"] = ""              # open ingest for the federation test
