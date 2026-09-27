"""MCP server (streamable HTTP) exposing the locally stored Garmin data to Claude."""
from __future__ import annotations

import csv
import io
import logging
import re
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import uvicorn
from mcp.server.fastmcp import FastMCP

from . import config, db, garmin, sync, workouts

log = logging.getLogger(__name__)

BASE_INSTRUCTIONS = """\
Running data from the athlete's Garmin Connect account, archived locally (SQLite + original FIT files).
- If the athlete talks about a run they just finished, call `sync_garmin` first to fetch it.
- Watch temperature is usually unreliable (body heat): prefer the real temperature the athlete gives you
  and store it with `annotate_activity`.
- Treadmill runs (type_key treadmill_running or annotation treadmill=1): pace, distance, stride length,
  vertical ratio and power come from the wrist and are unreliable; heart rate, cadence and the belt
  speed the athlete reports are the reliable values.
- Heart-rate recovery: if the last lap is ~1 minute standing still, `get_activity` reports HRR at 60".
- Structured workouts: call `create_workout` WITHOUT confirm first and show the preview; call it again
  with confirm=true only after the athlete approves. With `date` it is scheduled in the Garmin calendar
  and reaches the watch at the next sync.
- Units: pace min:ss/km, cadence steps/min, vertical oscillation cm, ground-contact balance left%/right%.
"""


def _instructions() -> str:
    text = BASE_INSTRUCTIONS
    try:
        extra = config.ATHLETE_FILE.read_text(encoding="utf-8").strip()
        if extra:
            text += "\nAthlete notes:\n" + extra + "\n"
            log.info("Loaded athlete notes from %s", config.ATHLETE_FILE)
    except FileNotFoundError:
        pass
    return text


mcp = FastMCP("garmin-coach", instructions=_instructions(),
              host=config.MCP_HOST, port=config.MCP_PORT)


# ---------------------------------------------------------------- formatting
def pace(speed):
    if not speed or speed <= 0.3:
        return ""
    s = 1000 / speed
    m, sec = divmod(round(s), 60)
    return f"{m}:{sec:02d}"


def hms(s):
    if s is None:
        return ""
    s = round(s)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def r1(x, nd=1):
    if x is None:
        return ""
    return int(round(x)) if nd == 0 else round(x, nd)


def to_csv(header, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


@contextmanager
def ro():
    db.init()
    conn = db.connect(readonly=True)
    try:
        yield conn
    finally:
        conn.close()


def _resolve_id(conn, activity_id: str) -> int | None:
    a = str(activity_id).strip().lower()
    if a in ("latest", "last", ""):
        row = conn.execute(
            "SELECT activity_id FROM activities WHERE type_key LIKE '%run%' "
            "ORDER BY start_local DESC LIMIT 1").fetchone()
        return row["activity_id"] if row else None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a):
        row = conn.execute(
            "SELECT activity_id FROM activities WHERE substr(start_local,1,10)=? "
            "AND type_key LIKE '%run%' ORDER BY start_local DESC LIMIT 1", (a,)).fetchone()
        return row["activity_id"] if row else None
    return int(a) if a.isdigit() else None


def _is_treadmill(act, ann) -> bool:
    if ann and ann["treadmill"] is not None:
        return bool(ann["treadmill"])
    return "treadmill" in (act["type_key"] or "") or "indoor" in (act["type_key"] or "")


def _band_labels():
    b = config.HR_BANDS
    labels = [f"<{b[0]}"]
    for lo, hi in zip(b, b[1:]):
        labels.append(f"{lo}-{hi - 1}")
    labels.append(f">={b[-1]}")
    return labels


def _band_idx(hr):
    return sum(1 for thr in config.HR_BANDS if hr >= thr)


def _hr_band_seconds(conn, aid: int) -> list[float]:
    secs = [0.0] * (len(config.HR_BANDS) + 1)
    rows = conn.execute("SELECT t_s, hr FROM records WHERE activity_id=? ORDER BY t_s",
                        (aid,)).fetchall()
    for cur, nxt in zip(rows, rows[1:]):
        if cur["hr"] is None:
            continue
        dt = min(nxt["t_s"] - cur["t_s"], 10)  # gaps > 10 s = pause
        secs[_band_idx(cur["hr"])] += dt
    return secs


def _hrr(conn, aid: int, laps) -> dict | None:
    """60" heart-rate recovery: last lap of about one minute with negligible distance."""
    if len(laps) < 2:
        return None
    last = laps[-1]
    dur = last["elapsed_s"] or 0
    if not (45 <= dur <= 100) or (last["distance_m"] or 0) > 150:
        return None
    t0 = last["start_offset_s"]
    if t0 is None:
        return None

    def hr_at(t):
        row = conn.execute(
            "SELECT hr FROM records WHERE activity_id=? AND hr IS NOT NULL "
            "ORDER BY abs(t_s - ?) LIMIT 1", (aid, t)).fetchone()
        return row["hr"] if row else None

    h0, h60 = hr_at(t0), hr_at(t0 + 60)
    if h0 is None or h60 is None:
        return None
    return {"hr_start": h0, "hr_60s": h60, "hrr_60": h0 - h60, "lap_s": round(dur)}


def _garmin_or_error():
    try:
        return garmin.client(), None
    except garmin.AuthRequired as e:
        return None, str(e)


# ---------------------------------------------------------------- activity tools
@mcp.tool()
def sync_garmin(full: bool = False, since: str | None = None, redetail: bool = False) -> str:
    """Fetch new activities from Garmin Connect (incremental, a few seconds).
    full=True: re-import everything since BACKFILL_FROM (slow: runs in background, check sync_status).
    since='YYYY-MM-DD': re-sync from that date. redetail=True: re-download FIT files already stored."""
    if full or (since and date.fromisoformat(since) < date.today() - timedelta(days=60)):
        threading.Thread(target=sync.run, kwargs=dict(since=since, full=full, redetail=redetail),
                         daemon=True).start()
        return "Long sync started in background. Check progress with sync_status."
    res = sync.run(since=since, redetail=redetail)
    out = [f"status: {res['status']}", f"new activities: {res.get('new_activities', 0)}",
           f"FIT files downloaded: {res.get('detailed', 0)}", res.get("message", "")]
    if res.get("new_ids"):
        with ro() as conn:
            q = ",".join("?" * len(res["new_ids"]))
            for r in conn.execute(
                    f"SELECT activity_id, start_local, type_key, name, distance_m FROM activities "
                    f"WHERE activity_id IN ({q}) ORDER BY start_local", res["new_ids"]):
                out.append(f"- {r['activity_id']} {r['start_local']} {r['type_key']} "
                           f"'{r['name']}' {r1((r['distance_m'] or 0) / 1000, 2)} km")
    return "\n".join(out)


@mcp.tool()
def sync_status() -> str:
    """Archive status: counts, period covered, latest syncs."""
    with ro() as conn:
        c = conn.execute(
            "SELECT count(*) n, sum(type_key LIKE '%run%') runs, sum(has_details=1) det, "
            "sum(has_details=-1) failed, min(start_local) first, max(start_local) last "
            "FROM activities").fetchone()
        logs = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 5").fetchall()
    out = [f"activities: {c['n']} (runs: {c['runs']}, with FIT/laps: {c['det']}, "
           f"failed downloads: {c['failed']})",
           f"period: {c['first']} → {c['last']}",
           f"sync running: {'yes' if sync._lock.locked() else 'no'}", "latest syncs:"]
    for r in logs:
        out.append(f"- {r['started_at']} {r['mode']} → {r['status']} "
                   f"(new {r['new_activities']}, FIT {r['detailed']}) {r['message']}")
    return "\n".join(out)


@mcp.tool()
def list_activities(start_date: str | None = None, end_date: str | None = None,
                    type_filter: str = "run", limit: int = 60) -> str:
    """List activities (CSV). Default: last 30 days, runs only.
    type_filter: substring of type_key ('run', 'treadmill', 'strength', '' = all)."""
    end_date = end_date or date.today().isoformat()
    start_date = start_date or (date.fromisoformat(end_date) - timedelta(days=30)).isoformat()
    with ro() as conn:
        rows = conn.execute(
            "SELECT a.*, n.real_temp_c, n.shoe, n.session_type, n.notes "
            "FROM activities a LEFT JOIN annotations n USING(activity_id) "
            "WHERE substr(start_local,1,10) BETWEEN ? AND ? AND coalesce(type_key,'') LIKE ? "
            "ORDER BY start_local DESC LIMIT ?",
            (start_date, end_date, f"%{type_filter}%", limit)).fetchall()
    header = ["id", "date", "time", "type", "name", "km", "duration", "pace", "hr_avg", "hr_max",
              "cadence", "te_aer", "load", "shoes", "real_temp", "session", "notes"]
    data = []
    for r in rows:
        data.append([r["activity_id"], (r["start_local"] or "")[:10], (r["start_local"] or "")[11:16],
                     r["type_key"], r["name"], r1((r["distance_m"] or 0) / 1000, 2),
                     hms(r["duration_s"]), pace(r["avg_speed"]), r1(r["avg_hr"], 0),
                     r1(r["max_hr"], 0), r1(r["avg_cadence"], 0), r1(r["aerobic_te"]),
                     r1(r["training_load"], 0), r["shoe"] or r["gear"] or "",
                     r1(r["real_temp_c"]), r["session_type"] or "", r["notes"] or ""])
    return f"{len(data)} activities {start_date} → {end_date}\n" + to_csv(header, data)


@mcp.tool()
def get_activity(activity_id: str = "latest", include_laps: bool = True) -> str:
    """Summary + laps (like Garmin's per-lap CSV export) + HRR60 + time in HR bands + annotations.
    activity_id: Garmin id, 'latest' (latest run) or a date 'YYYY-MM-DD'."""
    with ro() as conn:
        aid = _resolve_id(conn, activity_id)
        act = conn.execute("SELECT * FROM activities WHERE activity_id=?", (aid,)).fetchone() if aid else None
        if not act:
            return "Activity not found. Try sync_garmin or list_activities."
        ann = conn.execute("SELECT * FROM annotations WHERE activity_id=?", (aid,)).fetchone()
        laps = conn.execute("SELECT * FROM laps WHERE activity_id=? ORDER BY lap_index",
                            (aid,)).fetchall()
        out = [
            f"id {aid} | {act['start_local']} | {act['type_key']} | '{act['name']}'",
            f"distance {r1((act['distance_m'] or 0) / 1000, 2)} km | time {hms(act['duration_s'])} "
            f"(moving {hms(act['moving_s'])}, elapsed {hms(act['elapsed_s'])}) | "
            f"avg pace {pace(act['avg_speed'])}/km",
            f"HR avg {r1(act['avg_hr'], 0)} max {r1(act['max_hr'], 0)} | cadence {r1(act['avg_cadence'], 0)} | "
            f"GCT {r1(act['avg_gct_ms'], 0)} ms | vert. osc. {r1(act['avg_vo_cm'])} cm | "
            f"vert. ratio {r1(act['avg_vratio'])}% | stride {r1(act['avg_stride_m'], 2)} m | "
            f"power {r1(act['avg_power'], 0)} W",
            f"elevation +{r1(act['elev_gain'], 0)}/-{r1(act['elev_loss'], 0)} m | aerobic TE "
            f"{r1(act['aerobic_te'])} anaerobic {r1(act['anaerobic_te'])} | load {r1(act['training_load'], 0)} | "
            f"VO2max {r1(act['vo2max'], 0)} | Garmin shoes: {act['gear'] or '-'}",
        ]
        if ann:
            fields = {k: ann[k] for k in ann.keys() if k not in ("activity_id", "updated_at")
                      and ann[k] is not None}
            out.append("annotations: " + "; ".join(f"{k}={v}" for k, v in fields.items()))
        else:
            out.append("annotations: none (real temperature not recorded)")
        if _is_treadmill(act, ann):
            out.append("TREADMILL: ignore pace, distance, stride length, vertical ratio, power. "
                       "Reliable: HR, cadence, vertical oscillation, belt speed reported by the athlete.")
        if act["has_details"] != 1:
            out.append("(laps/records not available: FIT file not downloaded)")
        else:
            hrr = _hrr(conn, aid, laps)
            if hrr:
                out.append(f"HRR60 (last lap {hrr['lap_s']}s): {hrr['hr_start']} → "
                           f"{hrr['hr_60s']} = {hrr['hrr_60']} bpm")
            secs = _hr_band_seconds(conn, aid)
            tot = sum(secs) or 1
            out.append("time in HR bands: " + " | ".join(
                f"{lab}: {hms(s)} ({round(100 * s / tot)}%)" for lab, s in zip(_band_labels(), secs)))
        if include_laps and laps:
            header = ["lap", "trigger", "time", "km", "pace", "gap", "hr_avg", "hr_max", "cad",
                      "cad_max", "gct_ms", "bal_L/R", "vo_cm", "vr_%", "step_m", "watt",
                      "asc", "desc", "watch_temp"]
            data = []
            for l in laps:
                bal = (f"{l['gct_bal_left']:.1f}/{100 - l['gct_bal_left']:.1f}"
                       if l["gct_bal_left"] else "")
                data.append([l["lap_index"], l["trigger"], hms(l["timer_s"]),
                             r1((l["distance_m"] or 0) / 1000, 2), pace(l["avg_speed"]),
                             pace(l["gap_speed"]), r1(l["avg_hr"], 0), r1(l["max_hr"], 0),
                             r1(l["avg_cadence"], 0), r1(l["max_cadence"], 0), r1(l["gct_ms"], 0),
                             bal, r1(l["vo_cm"]), r1(l["vratio"]), r1(l["step_len_m"], 2),
                             r1(l["avg_power"], 0), r1(l["ascent_m"], 0), r1(l["descent_m"], 0),
                             r1(l["avg_temp"], 0)])
            out.append("")
            out.append(to_csv(header, data))
    return "\n".join(out)


@mcp.tool()
def get_activity_series(activity_id: str = "latest", every_s: int = 30,
                        from_s: int | None = None, to_s: int | None = None) -> str:
    """Downsampled time series (averages over every_s-second windows) from the FIT records.
    Useful for cardiac drift, blow-ups, intervals, analysis inside a lap. from_s/to_s = seconds from start."""
    every_s = max(1, int(every_s))
    with ro() as conn:
        aid = _resolve_id(conn, activity_id)
        if not aid:
            return "Activity not found."
        q = "SELECT * FROM records WHERE activity_id=?"
        args: list = [aid]
        if from_s is not None:
            q += " AND t_s >= ?"
            args.append(from_s)
        if to_s is not None:
            q += " AND t_s <= ?"
            args.append(to_s)
        rows = conn.execute(q + " ORDER BY t_s", args).fetchall()
    if not rows:
        return "No records (FIT file not downloaded?)."
    buckets = defaultdict(list)
    for r in rows:
        buckets[r["t_s"] // every_s].append(r)
    cols = ["speed", "hr", "cadence", "gct_ms", "gct_bal_left", "vo_cm", "vratio", "power", "altitude"]
    header = ["t", "km", "pace", "hr", "cad", "gct", "bal_L", "vo", "vr", "watt", "alt"]
    data = []
    for k in sorted(buckets):
        grp = buckets[k]
        avg = {}
        for c in cols:
            vals = [g[c] for g in grp if g[c] is not None]
            avg[c] = sum(vals) / len(vals) if vals else None
        dist = next((g["distance_m"] for g in reversed(grp) if g["distance_m"] is not None), None)
        data.append([hms(k * every_s), r1((dist or 0) / 1000, 2), pace(avg["speed"]),
                     r1(avg["hr"], 0), r1(avg["cadence"], 0), r1(avg["gct_ms"], 0),
                     r1(avg["gct_bal_left"]), r1(avg["vo_cm"]), r1(avg["vratio"]),
                     r1(avg["power"], 0), r1(avg["altitude"], 0)])
    return to_csv(header, data)


@mcp.tool()
def training_summary(weeks: int = 12, end_date: str | None = None) -> str:
    """Weekly running summary (Mon-Sun weeks): runs, km, time, average pace, longest run,
    training load and time distribution across the HR bands (HR_BANDS)."""
    end = date.fromisoformat(end_date) if end_date else date.today()
    end_monday = end - timedelta(days=end.weekday())
    start = end_monday - timedelta(weeks=weeks - 1)
    labels = _band_labels()
    with ro() as conn:
        acts = conn.execute(
            "SELECT a.*, n.treadmill tm FROM activities a LEFT JOIN annotations n USING(activity_id) "
            "WHERE type_key LIKE '%run%' AND substr(start_local,1,10) BETWEEN ? AND ? "
            "ORDER BY start_local", (start.isoformat(), end.isoformat())).fetchall()
        weeks_d: dict = {}
        for a in acts:
            d = date.fromisoformat(a["start_local"][:10])
            wk = d - timedelta(days=d.weekday())
            w = weeks_d.setdefault(wk, dict(n=0, km=0.0, s=0.0, longest=0.0, load=0.0, tm=0,
                                            bands=[0.0] * len(labels)))
            km = (a["distance_m"] or 0) / 1000
            w["n"] += 1
            w["km"] += km
            w["s"] += a["duration_s"] or 0
            w["longest"] = max(w["longest"], km)
            w["load"] += a["training_load"] or 0
            if a["tm"] or "treadmill" in (a["type_key"] or ""):
                w["tm"] += 1
            if a["has_details"] == 1:
                for i, s in enumerate(_hr_band_seconds(conn, a["activity_id"])):
                    w["bands"][i] += s
    header = ["week", "runs", "treadmill", "km", "time", "avg_pace", "longest_km", "load"] + \
             [f"hr {lab}" for lab in labels]
    data = []
    wk = start
    while wk <= end_monday:
        w = weeks_d.get(wk)
        if w:
            tot = sum(w["bands"]) or 1
            data.append([wk.isoformat(), w["n"], w["tm"], r1(w["km"]), hms(w["s"]),
                         pace(w["km"] * 1000 / w["s"]) if w["s"] else "", r1(w["longest"]),
                         r1(w["load"], 0)] + [f"{round(100 * b / tot)}%" for b in w["bands"]])
        else:
            data.append([wk.isoformat(), 0, 0, 0, "", "", "", ""] + [""] * len(labels))
        wk += timedelta(weeks=1)
    return to_csv(header, data)


@mcp.tool()
def annotate_activity(activity_id: str, real_temp_c: float | None = None,
                      humidity_pct: float | None = None, treadmill: bool | None = None,
                      shoe: str | None = None, session_type: str | None = None,
                      rpe: float | None = None, hrr_60: float | None = None,
                      notes: str | None = None) -> str:
    """Store information Garmin lacks or gets wrong (real temperature, treadmill, shoes,
    session type, RPE, manual HRR, notes). Only the given fields are updated; notes is replaced."""
    db.init()
    conn = db.connect()
    try:
        aid = _resolve_id(conn, activity_id)
        if not aid or not conn.execute("SELECT 1 FROM activities WHERE activity_id=?", (aid,)).fetchone():
            return "Activity not found."
        vals = dict(real_temp_c=real_temp_c, humidity_pct=humidity_pct,
                    treadmill=None if treadmill is None else int(treadmill), shoe=shoe,
                    session_type=session_type, rpe=rpe, hrr_60=hrr_60, notes=notes)
        vals = {k: v for k, v in vals.items() if v is not None}
        if not vals:
            return "Nothing to save."
        vals["updated_at"] = datetime.now().isoformat(timespec="seconds")
        conn.execute("INSERT OR IGNORE INTO annotations (activity_id) VALUES (?)", (aid,))
        conn.execute(f"UPDATE annotations SET {', '.join(f'{k}=?' for k in vals)} WHERE activity_id=?",
                     [*vals.values(), aid])
        conn.commit()
    finally:
        conn.close()
    return f"Annotation saved on {aid}: " + ", ".join(f"{k}={v}" for k, v in vals.items())


_SQL_OK = re.compile(r"^\s*(with|select)\b", re.I)


@mcp.tool()
def query_sql(sql: str, max_rows: int = 300) -> str:
    """Read-only SQL (SQLite) for free-form medium/long-term analysis.
    Tables:
    - activities(activity_id, start_local, start_gmt, name, type_key, distance_m, duration_s, moving_s,
      elapsed_s, avg_speed[m/s], avg_hr, max_hr, avg_cadence[steps/min], avg_power, elev_gain, elev_loss,
      calories, aerobic_te, anaerobic_te, training_load, vo2max, avg_gct_ms, avg_vo_cm, avg_vratio,
      avg_stride_m, gear, has_details, fit_path, raw_json[full Garmin JSON: use json_extract])
    - laps(activity_id, lap_index, start_time, start_offset_s, trigger, intensity, elapsed_s, timer_s,
      distance_m, avg_speed, max_speed, gap_speed, avg_hr, max_hr, avg_cadence, max_cadence, avg_power,
      max_power, gct_ms, gct_bal_left, vo_cm, vratio, step_len_m, ascent_m, descent_m, calories, avg_temp)
    - records(activity_id, t_s, distance_m, speed, hr, cadence, altitude, power, gct_ms, gct_bal_left,
      vo_cm, vratio, step_len_m, temp, lat, lon)  -- ~1 row/second: always filter by activity_id or aggregate
    - annotations(activity_id, real_temp_c, humidity_pct, treadmill, shoe, session_type, rpe, hrr_60, notes)
    - sync_log(...)
    Pace min/km = 1000/speed/60."""
    if not _SQL_OK.match(sql) or ";" in sql.strip().rstrip(";"):
        return "Only a single SELECT/WITH statement is allowed."
    max_rows = min(max(1, max_rows), 2000)
    with ro() as conn:
        t = time.time()
        cur = conn.execute(sql.strip().rstrip(";"))
        rows = cur.fetchmany(max_rows + 1)
        header = [d[0] for d in cur.description or []]
    more = len(rows) > max_rows
    rows = rows[:max_rows]
    res = to_csv(header, [list(r) for r in rows])
    return res + (f"... (truncated to {max_rows} rows)\n" if more else "") + \
        f"[{len(rows)} rows, {time.time() - t:.2f}s]"


# ---------------------------------------------------------------- structured workouts
@mcp.tool()
def create_workout(name: str, steps: list[dict], date: str | None = None,
                   description: str | None = None, confirm: bool = False,
                   replace_workout_id: str | None = None) -> str:
    """Create a structured running workout in Garmin Connect and, if date='YYYY-MM-DD',
    schedule it in the calendar so it reaches the watch at the next sync.
    Without confirm=true it only returns a preview: show it to the athlete, then call again with confirm=true.
    replace_workout_id: rewrite an existing workout in place (id and calendar dates are kept; don't pass date).

    steps: ordered list of steps. Simple step:
      {"kind": "warmup|interval|recovery|rest|cooldown|other",
       duration (one): "time": "mm:ss" | "distance_km": 2 | "distance_m": 400 | "lap": true,
       target (optional, one): "pace": "5:40-5:45" (min/km) | "hr": "150-160" (bpm),
       "note": "short text shown on the watch"}
    Repeat: {"repeat": 3, "steps": [ ...steps... ]}
    Example: [{"kind":"warmup","time":"15:00","hr":"120-145"},
              {"repeat":3,"steps":[{"kind":"interval","distance_km":2,"pace":"5:40-5:45"},
                                   {"kind":"recovery","time":"2:00","note":"easy jog"}]},
              {"kind":"cooldown","time":"10:00"}]"""
    try:
        payload, preview = workouts.build(name, steps, description)
    except workouts.WorkoutError as e:
        return f"Invalid steps: {e}"
    if date:
        date = date.strip()
        preview += f"\nScheduled on: {date}"
    if replace_workout_id:
        preview += f"\nReplaces workout {replace_workout_id}"
    if not confirm:
        return "PREVIEW (not uploaded yet):\n" + preview
    g, err = _garmin_or_error()
    if err:
        return err
    if replace_workout_id:
        g.update_workout(replace_workout_id, payload)
        garmin.persist(g)
        return f"Workout {replace_workout_id} rewritten in place (calendar unchanged)\n" + preview
    res = g.upload_workout(payload)
    wid = res.get("workoutId")
    out = [f"Workout uploaded: id {wid}", preview]
    if date and wid:
        try:
            sch = g.schedule_workout(wid, date)
            out.append(f"Scheduled on {date} (scheduled id {(sch or {}).get('workoutScheduleId', '?')})")
        except Exception as e:  # noqa: BLE001
            out.append(f"Uploaded but NOT scheduled: {type(e).__name__}: {e}")
    garmin.persist(g)
    return "\n".join(out)


@mcp.tool()
def get_workout(workout_id: str) -> str:
    """Show the steps of a workout stored in Garmin Connect (durations, targets, notes)."""
    g, err = _garmin_or_error()
    if err:
        return err
    w = g.get_workout_by_id(workout_id)
    garmin.persist(g)
    return workouts.describe(w)


@mcp.tool()
def list_workouts(months_ahead: int = 1, library_limit: int = 15) -> str:
    """Workouts scheduled in the Garmin calendar (current month + months_ahead) and latest in the library."""
    g, err = _garmin_or_error()
    if err:
        return err
    out = ["Scheduled:"]
    y, m = date.today().year, date.today().month
    seen = set()
    for _ in range(months_ahead + 1):
        data = g.get_scheduled_workouts(y, m) or {}
        for it in sorted(data.get("calendarItems") or [], key=lambda x: x.get("date") or ""):
            if it.get("itemType") == "workout" and it.get("id") not in seen:
                seen.add(it.get("id"))
                out.append(f"- {it.get('date')} '{it.get('title')}' workout {it.get('workoutId')} "
                           f"scheduled {it.get('id')}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    out.append("Library (most recent):")
    for w in (g.get_workouts(0, library_limit) or []):
        out.append(f"- {w.get('workoutId')} '{w.get('workoutName')}' "
                   f"({(w.get('sportType') or {}).get('sportTypeKey')})")
    garmin.persist(g)
    return "\n".join(out)


@mcp.tool()
def delete_workout(workout_id: str | None = None, scheduled_id: str | None = None) -> str:
    """Remove a workout from the calendar (scheduled_id) and/or delete it from the library (workout_id).
    Only use when the athlete explicitly asks for it."""
    g, err = _garmin_or_error()
    if err:
        return err
    out = []
    if scheduled_id:
        g.unschedule_workout(scheduled_id)
        out.append(f"Removed from calendar: {scheduled_id}")
    if workout_id:
        g.delete_workout(workout_id)
        out.append(f"Deleted from library: {workout_id}")
    garmin.persist(g)
    return "\n".join(out) or "Nothing to do: pass workout_id and/or scheduled_id."


# ---------------------------------------------------------------- startup
class BearerAuth:
    """ASGI middleware: requires 'Authorization: Bearer <MCP_TOKEN>' when configured.
    /healthz is always open."""

    def __init__(self, app, token: str | None):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/healthz":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ok"})
            return
        if scope["type"] == "http" and self.token:
            hdrs = dict(scope.get("headers") or [])
            if hdrs.get(b"authorization", b"").decode() != f"Bearer {self.token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


def _scheduler():
    time.sleep(5)
    while True:
        try:
            res = sync.run()
            log.info("Auto sync: %s, new %s, FIT %s. %s", res["status"], res.get("new_activities"),
                     res.get("detailed"), res.get("message"))
        except Exception:  # noqa: BLE001
            log.exception("Auto sync failed")
        if config.SYNC_INTERVAL_MIN <= 0:
            return
        time.sleep(config.SYNC_INTERVAL_MIN * 60)


def serve():
    db.init()
    if config.SYNC_INTERVAL_MIN > 0:
        threading.Thread(target=_scheduler, daemon=True).start()
    if not config.MCP_TOKEN:
        log.warning("MCP_TOKEN not set: the server is running WITHOUT authentication")
    app = BearerAuth(mcp.streamable_http_app(), config.MCP_TOKEN)
    uvicorn.run(app, host=config.MCP_HOST, port=config.MCP_PORT, log_level="info")
