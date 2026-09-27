"""Garmin Connect -> SQLite sync.

- incremental: from the latest stored activity (minus 3 days) to today
- full/backfill: from BACKFILL_FROM (or a given date)
For runs it downloads the original FIT file and extracts laps and records.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta

from garminconnect import Garmin
from garminconnect.exceptions import GarminConnectTooManyRequestsError

from . import config, db, fitfile, garmin

log = logging.getLogger(__name__)
_lock = threading.Lock()

LAP_COLS = ["lap_index", "start_time", "start_offset_s", "trigger", "intensity", "elapsed_s",
            "timer_s", "distance_m", "avg_speed", "max_speed", "gap_speed", "avg_hr", "max_hr",
            "avg_cadence", "max_cadence", "avg_power", "max_power", "gct_ms", "gct_bal_left",
            "vo_cm", "vratio", "step_len_m", "ascent_m", "descent_m", "calories", "avg_temp"]
REC_COLS = ["t_s", "distance_m", "speed", "hr", "cadence", "altitude", "power", "gct_ms",
            "gct_bal_left", "vo_cm", "vratio", "step_len_m", "temp", "lat", "lon"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _summary_row(a: dict) -> dict:
    at = a.get("activityType") or {}
    return dict(
        activity_id=a["activityId"],
        start_local=a.get("startTimeLocal"),
        start_gmt=a.get("startTimeGMT"),
        name=a.get("activityName"),
        type_key=at.get("typeKey"),
        distance_m=a.get("distance"),
        duration_s=a.get("duration"),
        moving_s=a.get("movingDuration"),
        elapsed_s=a.get("elapsedDuration"),
        avg_speed=a.get("averageSpeed"),
        avg_hr=a.get("averageHR"),
        max_hr=a.get("maxHR"),
        avg_cadence=a.get("averageRunningCadenceInStepsPerMinute"),
        avg_power=a.get("avgPower"),
        elev_gain=a.get("elevationGain"),
        elev_loss=a.get("elevationLoss"),
        calories=a.get("calories"),
        aerobic_te=a.get("aerobicTrainingEffect"),
        anaerobic_te=a.get("anaerobicTrainingEffect"),
        training_load=a.get("activityTrainingLoad"),
        vo2max=a.get("vO2MaxValue"),
        avg_gct_ms=a.get("avgGroundContactTime"),
        avg_vo_cm=a.get("avgVerticalOscillation"),
        avg_vratio=a.get("avgVerticalRatio"),
        avg_stride_m=(a["avgStrideLength"] / 100) if a.get("avgStrideLength") else None,
        raw_json=json.dumps(a, ensure_ascii=False),
        synced_at=_now(),
    )


def _upsert_activity(conn, row: dict) -> bool:
    exists = conn.execute("SELECT 1 FROM activities WHERE activity_id=?",
                          (row["activity_id"],)).fetchone() is not None
    cols = list(row)
    upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "activity_id")
    conn.execute(
        f"INSERT INTO activities ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT(activity_id) DO UPDATE SET {upd}",
        [row[c] for c in cols],
    )
    return not exists


def _gap_by_lap(g: Garmin, aid: int) -> dict[int, float]:
    try:
        sp = g.get_activity_splits(str(aid)) or {}
    except Exception as e:  # noqa: BLE001
        log.debug("splits %s: %s", aid, e)
        return {}
    out = {}
    for i, lap in enumerate(sp.get("lapDTOs") or [], start=1):
        idx = lap.get("lapIndex") or i
        if lap.get("avgGradeAdjustedSpeed"):
            out[int(idx)] = lap["avgGradeAdjustedSpeed"]
    return out


def _gear_name(g: Garmin, aid: int) -> str | None:
    try:
        gear = g.get_activity_gear(aid) or []
    except Exception as e:  # noqa: BLE001
        log.debug("gear %s: %s", aid, e)
        return None
    names = [x.get("displayName") or x.get("customMakeModel") or x.get("modelName")
             for x in gear if isinstance(x, dict)]
    names = [n for n in names if n]
    return ", ".join(names) or None


def load_details(conn, g: Garmin, aid: int) -> None:
    blob = g.download_activity(str(aid), dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    fit_bytes = fitfile.extract_fit(blob)
    config.FIT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.FIT_DIR / f"{aid}.fit"
    path.write_bytes(fit_bytes)
    store_fit(conn, aid, path)
    time.sleep(config.REQUEST_DELAY_S)

    gap = _gap_by_lap(g, aid)
    for idx, v in gap.items():
        conn.execute("UPDATE laps SET gap_speed=? WHERE activity_id=? AND lap_index=?",
                     (v, aid, idx))
    time.sleep(config.REQUEST_DELAY_S)

    gear = _gear_name(g, aid)
    conn.execute("UPDATE activities SET gear=? WHERE activity_id=?", (gear, aid))


def store_fit(conn, aid: int, path) -> None:
    """Parse a FIT file already on disk and (re)write laps and records."""
    parsed = fitfile.parse(path)
    old_gap = {r[0]: r[1] for r in conn.execute(
        "SELECT lap_index, gap_speed FROM laps WHERE activity_id=?", (aid,))}
    for lap in parsed["laps"]:
        lap["gap_speed"] = old_gap.get(lap["lap_index"])
    conn.execute("DELETE FROM laps WHERE activity_id=?", (aid,))
    conn.execute("DELETE FROM records WHERE activity_id=?", (aid,))
    conn.executemany(
        f"INSERT INTO laps (activity_id, {', '.join(LAP_COLS)}) "
        f"VALUES (?, {', '.join('?' * len(LAP_COLS))})",
        [[aid] + [lap.get(c) for c in LAP_COLS] for lap in parsed["laps"]],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO records (activity_id, {', '.join(REC_COLS)}) "
        f"VALUES (?, {', '.join('?' * len(REC_COLS))})",
        [[aid] + [r.get(c) for c in REC_COLS] for r in parsed["records"]],
    )
    conn.execute("UPDATE activities SET has_details=1, fit_path=? WHERE activity_id=?",
                 (str(path), aid))


def _start_date(conn, since: str | None, full: bool) -> str:
    if since:
        return since
    if full:
        return config.BACKFILL_FROM
    row = conn.execute("SELECT max(substr(start_local,1,10)) d FROM activities").fetchone()
    if not row or not row["d"]:
        return config.BACKFILL_FROM
    return (date.fromisoformat(row["d"]) - timedelta(days=3)).isoformat()


def run(since: str | None = None, full: bool = False, redetail: bool = False) -> dict:
    """Run a sync. Returns a summary dict."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "message": "A sync is already running"}
    db.init()
    conn = db.connect()
    started = _now()
    mode = "full" if full else ("since " + since if since else "incremental")
    new, detailed, status, msg = 0, 0, "ok", ""
    new_ids: list[int] = []
    try:
        g = garmin.client()
        start = _start_date(conn, since, full)
        end = date.today().isoformat()
        log.info("Sync %s: %s -> %s", mode, start, end)
        acts = g.get_activities_by_date(start, end, sortorder="asc") or []
        for a in acts:
            row = _summary_row(a)
            if _upsert_activity(conn, row):
                new += 1
                new_ids.append(row["activity_id"])
        conn.commit()

        # missing details (including earlier failures) + optional forced re-download
        todo = conn.execute(
            "SELECT activity_id, type_key FROM activities "
            "WHERE has_details=0 OR (? AND substr(start_local,1,10) >= ?) ORDER BY start_local",
            (1 if redetail else 0, start),
        ).fetchall()
        for r in todo:
            if not config.wants_details(r["type_key"]):
                continue
            try:
                load_details(conn, g, r["activity_id"])
                conn.commit()
                detailed += 1
                log.info("Details %s (%s) ok", r["activity_id"], r["type_key"])
            except GarminConnectTooManyRequestsError:
                raise
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                # -1 = failed: not retried on every sync (force with redetail)
                conn.execute("UPDATE activities SET has_details=-1 WHERE activity_id=?",
                             (r["activity_id"],))
                conn.commit()
                log.warning("Details %s failed: %s", r["activity_id"], e)
            time.sleep(config.REQUEST_DELAY_S)
        garmin.persist(g)
        msg = f"{len(acts)} activities read from Garmin ({start} → {end})"
    except garmin.AuthRequired as e:
        status, msg = "auth_required", str(e)
    except GarminConnectTooManyRequestsError as e:
        status, msg = "rate_limited", f"Rate limited by Garmin (429): try again later. {e}"
    except Exception as e:  # noqa: BLE001
        status, msg = "error", f"{type(e).__name__}: {e}"
        log.exception("Sync failed")
    finally:
        conn.execute(
            "INSERT INTO sync_log (started_at, finished_at, mode, new_activities, detailed, status, message) "
            "VALUES (?,?,?,?,?,?,?)", (started, _now(), mode, new, detailed, status, msg))
        conn.commit()
        conn.close()
        _lock.release()
    return {"status": status, "mode": mode, "new_activities": new, "new_ids": new_ids,
            "detailed": detailed, "message": msg}


def reparse_all() -> int:
    """Rebuild laps/records from all FIT files on disk (after parser changes)."""
    db.init()
    n = 0
    with db.connect() as conn:
        for r in conn.execute("SELECT activity_id FROM activities").fetchall():
            p = config.FIT_DIR / f"{r['activity_id']}.fit"
            if p.exists():
                store_fit(conn, r["activity_id"], p)
                n += 1
    return n
