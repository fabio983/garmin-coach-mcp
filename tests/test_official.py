"""official.Client paging and error mapping with fake Garmin classes."""
import importlib
import time

import pytest
from garmin_personal_api import BearerToken, HttpError


def _client(tmp_path, monkeypatch, pages, fail=None):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REQUEST_DELAY_S", "0")
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "k")
    from app import config, official
    importlib.reload(config)
    importlib.reload(official)

    class Auth:
        def __init__(self, **kw): pass
        def obtain_token(self, key, force_refresh=False):
            return BearerToken(access_token="t", expires_at=time.time() + 86400)
        def close(self): pass

    class Api:
        def __init__(self, token): pass
        def update_bearer_token(self, t): pass
        def close(self): pass
        def search_activities(self, start=0, limit=100):
            if fail:
                raise HttpError(status_code=fail, method="GET", url="u", response_text="")
            return pages.get(start, [])
        def get_activity_workouts(self, aid):
            raise HttpError(status_code=404, method="GET", url="u", response_text="")

    monkeypatch.setattr(official, "PersonalApiAuthenticator", Auth)
    monkeypatch.setattr(official, "GarminPersonalApiClient", Api)
    return official, official.Client()


def _acts(n, day0):
    return [{"activityId": i, "startTimeLocal": f"2026-{day0 - i // 28:02d}-{28 - i % 28:02d} 08:00:00"}
            for i in range(n)]


def test_paging_stops_at_start_date(tmp_path, monkeypatch):
    acts = _acts(150, 10)
    official, c = _client(tmp_path, monkeypatch, {0: acts[:100], 100: acts[100:]})
    got = list(c.activities_since("2026-07-01"))
    assert got and all(a["startTimeLocal"][:10] >= "2026-07-01" for a in got)
    assert len(got) == len([a for a in acts if a["startTimeLocal"][:10] >= "2026-07-01"])


def test_no_planned_workout_is_empty_list(tmp_path, monkeypatch):
    official, c = _client(tmp_path, monkeypatch, {})
    assert c.activity_workouts(1) == []


@pytest.mark.parametrize("code,exc", [(403, "AuthError"), (429, "RateLimited")])
def test_error_mapping(tmp_path, monkeypatch, code, exc):
    official, c = _client(tmp_path, monkeypatch, {}, fail=code)
    with pytest.raises(getattr(official, exc)):
        list(c.activities_since("2026-01-01"))
