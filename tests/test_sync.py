"""Sync tests with fake Garmin clients (no network)."""
import asyncio
import importlib
import io
import sqlite3
import zipfile
from pathlib import Path

SAMPLE = (Path(__file__).parent / "sample_run.fit").read_bytes()


def _zip(b):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1_ACTIVITY.fit", b)
    return buf.getvalue()


ACTS = [
    {"activityId": 2, "startTimeLocal": "2026-10-22 08:00:00", "activityName": "Strength",
     "activityType": {"typeKey": "strength_training"}, "duration": 1800},
    {"activityId": 1, "startTimeLocal": "2026-10-20 08:00:00", "activityName": "Easy run",
     "activityType": {"typeKey": "running"}, "distance": 157.6, "duration": 57, "averageSpeed": 2.77},
    {"activityId": 9, "startTimeLocal": "2023-01-01 08:00:00", "activityName": "Too old",
     "activityType": {"typeKey": "running"}},
]


class FakeOfficial:
    def __init__(self):
        pass

    def activities_since(self, start):
        return [a for a in ACTS if a["startTimeLocal"][:10] >= start]

    def download_activity(self, aid):
        return _zip(SAMPLE)

    def activity_workouts(self, aid):
        return [{"workoutName": "Easy 45'", "sport": "RUNNING"}]

    def close(self):
        pass


class FakeCommunity:
    class client:
        @staticmethod
        def dump(path):
            pass

    def get_activity_splits(self, aid):
        return {"lapDTOs": [{"lapIndex": 1, "avgGradeAdjustedSpeed": 2.9}]}

    def get_activity_gear(self, aid):
        return [{"displayName": "Shoe X"}]


def _reload(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REQUEST_DELAY_S", "0")
    monkeypatch.setenv("BACKFILL_FROM", "2024-01-01")
    for k in ("GARMIN_PERSONAL_API_KEY", "ENABLE_GARMINCONNECT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app import config, db, fitfile, garmin, official, sync
    for m in (config, db, fitfile, garmin, official, sync):
        importlib.reload(m)
    monkeypatch.setattr(official, "Client", FakeOfficial)
    monkeypatch.setattr(garmin, "client", lambda: FakeCommunity())
    return sync


def test_official_read_only(tmp_path, monkeypatch):
    sync = _reload(tmp_path, monkeypatch, GARMIN_PERSONAL_API_KEY="k")
    res = sync.run()
    assert res["status"] == "ok" and res["source"] == "official"
    assert res["new_activities"] == 2 and res["detailed"] == 1  # strength: summary only
    c = sqlite3.connect(tmp_path / "garmin.db")
    assert c.execute("select planned_workout, source, gear from activities where activity_id=1").fetchone() \
        == ("Easy 45'", "official", None)
    assert c.execute("select count(*), max(gap_speed) from laps where activity_id=1").fetchone() == (1, None)
    assert c.execute("select count(*) from records where activity_id=1").fetchone()[0] > 0


def test_official_plus_community_enrichment(tmp_path, monkeypatch):
    sync = _reload(tmp_path, monkeypatch, GARMIN_PERSONAL_API_KEY="k", ENABLE_GARMINCONNECT="true")
    assert sync.run()["status"] == "ok"
    c = sqlite3.connect(tmp_path / "garmin.db")
    assert c.execute("select gear from activities where activity_id=1").fetchone()[0] == "Shoe X"
    assert c.execute("select gap_speed from laps where activity_id=1").fetchone()[0] == 2.9


def test_not_configured(tmp_path, monkeypatch):
    sync = _reload(tmp_path, monkeypatch)
    res = sync.run()
    assert res["status"] == "auth_required" and "GARMIN_PERSONAL_API_KEY" in res["message"]


def test_workout_tools_need_community_module(tmp_path, monkeypatch):
    _reload(tmp_path, monkeypatch, GARMIN_PERSONAL_API_KEY="k")
    from app import garmin, server
    importlib.reload(garmin)  # real client(): raises Disabled
    importlib.reload(server)
    steps = [{"kind": "interval", "distance_km": 1, "pace": "5:00-5:10"}]
    call = lambda n, a: (lambda r: (r[0] if isinstance(r, tuple) else r)[0].text)(
        asyncio.run(server.mcp.call_tool(n, a)))
    assert "PREVIEW" in call("create_workout", {"name": "x", "steps": steps})
    out = call("create_workout", {"name": "x", "steps": steps, "confirm": True})
    assert "read-only" in out and "ENABLE_GARMINCONNECT=true" in out
    assert "ENABLE_GARMINCONNECT=true" in call("list_workouts", {})
