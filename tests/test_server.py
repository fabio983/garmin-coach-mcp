"""Tool tests on a synthetic database (no Garmin access)."""
import asyncio
import importlib
import sqlite3


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HR_BANDS", "140,150,160,170")
    from app import config, db
    importlib.reload(config)
    importlib.reload(db)
    db.init()
    c = sqlite3.connect(tmp_path / "garmin.db")
    c.execute("INSERT INTO activities(activity_id,start_local,name,type_key,distance_m,duration_s,"
              "avg_speed,avg_hr,max_hr,avg_cadence,has_details) "
              "VALUES (1,'2026-09-23 07:00:00','Tempo','running',3000,1080,2.78,155,170,172,1)")
    t = d = 0
    for k in range(3):  # 3 x 1 km laps
        c.execute("INSERT INTO laps(activity_id,lap_index,start_offset_s,trigger,elapsed_s,timer_s,"
                  "distance_m,avg_speed,avg_hr,gct_bal_left) VALUES (1,?,?,?,360,360,1000,2.78,?,48.5)",
                  (k + 1, t, "distance", 145 + 10 * k))
        for _ in range(360):
            d += 2.78
            c.execute("INSERT INTO records(activity_id,t_s,distance_m,speed,hr,cadence) "
                      "VALUES (1,?,?,2.78,?,172)", (t, d, 145 + 10 * k))
            t += 1
    c.execute("INSERT INTO laps(activity_id,lap_index,start_offset_s,trigger,elapsed_s,timer_s,distance_m) "
              "VALUES (1,4,?, 'manual',62,62,3)", (t,))
    for s in range(62):
        c.execute("INSERT INTO records(activity_id,t_s,distance_m,speed,hr) VALUES (1,?,?,0,?)",
                  (t, d, 170 - s // 3))
        t += 1
    c.commit()
    from app import server
    importlib.reload(server)
    return server


def _call(server, name, args):
    res = asyncio.run(server.mcp.call_tool(name, args))
    content = res[0] if isinstance(res, tuple) else res
    return content[0].text


def test_get_activity(tmp_path, monkeypatch):
    server = _setup(tmp_path, monkeypatch)
    out = _call(server, "get_activity", {"activity_id": "latest"})
    assert "HRR60 (last lap 62s): 170 → 150 = 20 bpm" in out
    assert "48.5/51.5" in out
    assert "140-149: 6:00" in out


def test_annotate_and_list(tmp_path, monkeypatch):
    server = _setup(tmp_path, monkeypatch)
    assert "real_temp_c=21.0" in _call(server, "annotate_activity",
                                       {"activity_id": "2026-09-23", "real_temp_c": 21})
    out = _call(server, "list_activities", {"start_date": "2026-09-01", "end_date": "2026-09-30"})
    assert "Tempo" in out and ",21.0," in out


def test_query_sql_read_only(tmp_path, monkeypatch):
    server = _setup(tmp_path, monkeypatch)
    assert "Only a single" in _call(server, "query_sql", {"sql": "delete from activities"})
    assert "[1 rows" in _call(server, "query_sql", {"sql": "select count(*) from activities"})
