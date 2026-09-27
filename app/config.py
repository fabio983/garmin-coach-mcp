"""Configuration from environment variables."""
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


DATA_DIR = Path(_env("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "garmin.db"
FIT_DIR = DATA_DIR / "fit"
TOKEN_DIR = DATA_DIR / "tokens"
# Optional personal notes for Claude (sensors, zones, quirks...). Appended to the server instructions.
ATHLETE_FILE = Path(_env("ATHLETE_FILE", str(DATA_DIR / "athlete.md")))

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL") or None
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD") or None

# First import: fetch history from this date on
BACKFILL_FROM = _env("BACKFILL_FROM", "2024-01-01")
# Background sync interval in minutes (0 = on demand only)
SYNC_INTERVAL_MIN = int(_env("SYNC_INTERVAL_MIN", "30"))
# Pause between Garmin requests, to stay below rate limits
REQUEST_DELAY_S = float(_env("REQUEST_DELAY_S", "1.5"))
# Activity types (substring of Garmin typeKey) for which FIT, laps and records are downloaded
DETAIL_TYPE_MATCH = [s.strip() for s in _env("DETAIL_TYPE_MATCH", "run").split(",") if s.strip()]

# Heart-rate bands for time-in-zone: lower bound (bpm) of bands 2..N.
# Placeholder defaults: set your own in .env
HR_BANDS = [int(x) for x in _env("HR_BANDS", "135,150,160,170").split(",")]

MCP_HOST = _env("MCP_HOST", "0.0.0.0")
MCP_PORT = int(_env("MCP_PORT", "8765"))
MCP_TOKEN = os.getenv("MCP_TOKEN") or None


def wants_details(type_key: str | None) -> bool:
    t = (type_key or "").lower()
    return any(m.lower() in t for m in DETAIL_TYPE_MATCH)
