#!/usr/bin/env python3
"""Probe the official Garmin Connect Personal API and compare it with the local archive.

Read-only: it never writes to Garmin nor to the local database. Prints a report to stdout
(no secrets). Run it with the one-off container command in tools/README.md.

Checks:
  1. API key -> bearer token exchange
  2. activity search: fields available, total activities reachable, oldest date (history depth)
  3. activity details: fields, and whether lap/split and gear endpoints answer
  4. original file download for a few recent runs, compared with the FIT already archived
     (byte identity, message types, laps, per-second records, running dynamics, session fields)
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import fitdecode
from garmin_personal_api import (GarminPersonalApiClient, GarminPersonalApiError, HttpError,
                                 PersonalApiAuthenticator, resolve_api_key)

DATA = Path(os.getenv("DATA_DIR", "/data"))
DELAY = 1.0
RUN_DYNAMICS = ["heart_rate", "cadence", "enhanced_speed", "stance_time", "stance_time_balance",
                "vertical_oscillation", "vertical_ratio", "step_length", "power", "position_lat",
                "enhanced_altitude", "temperature"]


def h(title):
    print(f"\n=== {title} " + "=" * max(0, 70 - len(title)))


def safe(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except HttpError as e:
        return None, f"HTTP {e.status_code}"
    except GarminPersonalApiError as e:
        return None, f"error: {e}"
    finally:
        time.sleep(DELAY)


def as_list(res):
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        for k in ("activityList", "activities", "items", "results"):
            if isinstance(res.get(k), list):
                return res[k]
    return []


def fit_profile(blob: bytes) -> dict:
    """Message counts, lap/record counts, non-null share of running-dynamics fields, session keys."""
    msgs = collections.Counter()
    rec_fields = collections.Counter()
    n_rec = 0
    session = {}
    with fitdecode.FitReader(io.BytesIO(blob), check_crc=fitdecode.CrcCheck.DISABLED) as r:
        for f in r:
            if not isinstance(f, fitdecode.FitDataMessage):
                continue
            msgs[f.name] += 1
            if f.name == "record":
                n_rec += 1
                for fld in RUN_DYNAMICS:
                    if f.has_field(fld) and f.get_value(fld) is not None:
                        rec_fields[fld] += 1
            elif f.name == "session" and not session:
                session = {fl.name: fl.value for fl in f.fields if fl.value is not None
                           and not str(fl.name).startswith("unknown")}
    return {"messages": msgs, "records": n_rec,
            "fields": {k: round(100 * rec_fields[k] / n_rec) if n_rec else 0 for k in RUN_DYNAMICS},
            "session": session}


def extract_fit(blob: bytes) -> bytes:
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = z.namelist()
            fits = [n for n in names if n.lower().endswith(".fit")]
            print(f"   zip content: {names}")
            if not fits:
                raise ValueError("no .fit file in the zip")
            return z.read(fits[0])
    return blob


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3, help="recent runs to download and compare")
    ap.add_argument("--max-pages", type=int, default=30, help="search pages (x100) for history depth")
    args = ap.parse_args()

    h("1. Authentication")
    try:
        key = resolve_api_key()
    except GarminPersonalApiError as e:
        sys.exit(f"No API key: {e}\nSet GARMIN_PERSONAL_API_KEY in .env")
    cache = Path(tempfile.gettempdir()) / "gpa-token.json"
    with PersonalApiAuthenticator(bearer_token_cache_file=cache) as auth:
        try:
            tok = auth.obtain_token(key)
        except HttpError as e:
            sys.exit(f"Token exchange failed: HTTP {e.status_code} {e.response_text[:200]}")
    print(f"OK, bearer token valid for {round((tok.expires_at - time.time()) / 3600, 1)} h")
    api = GarminPersonalApiClient(tok.access_token)

    db = None
    if (DATA / "garmin.db").exists():
        db = sqlite3.connect(f"file:{DATA / 'garmin.db'}?mode=ro&immutable=1", uri=True)
        db.row_factory = sqlite3.Row

    h("2. Activity search")
    first, err = safe(api.search_activities, start=0, limit=5)
    items = as_list(first)
    if err or not items:
        sys.exit(f"search failed: {err or 'empty response'} -> {str(first)[:300]}")
    a0 = items[0]
    print(f"latest: {a0.get('activityId')} {a0.get('startTimeLocal')} "
          f"{(a0.get('activityType') or {}).get('typeKey')} '{a0.get('activityName')}'")
    keys = sorted(a0.keys())
    print(f"summary fields ({len(keys)}): {', '.join(keys)}")
    if db:
        cols_needed = ["averageRunningCadenceInStepsPerMinute", "avgGroundContactTime",
                       "avgVerticalOscillation", "avgVerticalRatio", "avgStrideLength", "avgPower",
                       "aerobicTrainingEffect", "activityTrainingLoad", "vO2MaxValue"]
        missing = [c for c in cols_needed if c not in a0]
        print(f"fields used by garmin-coach missing here: {missing or 'none'}")

    total, oldest, page = 0, None, 0
    while page < args.max_pages:
        res, err = safe(api.search_activities, start=page * 100, limit=100)
        lst = as_list(res)
        if err:
            print(f"page {page}: {err}")
            break
        if not lst:
            break
        total += len(lst)
        oldest = lst[-1].get("startTimeLocal")
        page += 1
    print(f"activities reachable: {total}{'+' if page >= args.max_pages else ''}, oldest: {oldest}")
    if db:
        r = db.execute("SELECT count(*) n, min(start_local) first FROM activities").fetchone()
        print(f"local archive: {r['n']} activities, oldest {r['first']}")

    h("3. Activity details and extra endpoints")
    runs = [a for a in items if "run" in str((a.get("activityType") or {}).get("typeKey"))]
    if len(runs) < args.runs:
        more, _ = safe(api.search_activities, start=0, limit=40)
        runs = [a for a in as_list(more) if "run" in str((a.get("activityType") or {}).get("typeKey"))]
    runs = runs[:args.runs]
    if not runs:
        sys.exit("no recent runs found")
    aid = runs[0]["activityId"]
    det, err = safe(api.get_activity, aid)
    print(f"get_activity({aid}): {err or 'OK'}; top-level keys: "
          f"{', '.join(sorted(det.keys())) if isinstance(det, dict) else type(det).__name__}")
    for label, path in [("splits/laps", f"/activity-service/activity/{aid}/splits"),
                        ("split summaries", f"/activity-service/activity/{aid}/split_summaries"),
                        ("details/metrics", f"/activity-service/activity/{aid}/details"),
                        ("gear", "/gear-service/gear/filterGear"),
                        ("hr time in zones", f"/activity-service/activity/{aid}/hrTimeInZones")]:
        params = {"activityId": aid} if "gear" in path else None
        res, err = safe(api.get, path, params=params)
        extra = ""
        if res is not None and not err:
            if isinstance(res, dict) and "lapDTOs" in res:
                laps = res["lapDTOs"]
                gap = sum(1 for l in laps if l.get("avgGradeAdjustedSpeed"))
                extra = f" ({len(laps)} laps, {gap} with grade-adjusted pace)"
            elif isinstance(res, list):
                extra = f" (list of {len(res)})"
        print(f"{label:17}: {err or 'OK'}{extra}")
    wk, err = safe(api.get_activity_workouts, aid)
    print(f"{'activity workouts':17}: {err or 'OK'} {str(wk)[:120] if wk else ''}")

    h("4. Original file vs archived FIT")
    for a in runs:
        aid = a["activityId"]
        print(f"\n-- {aid} {a.get('startTimeLocal')} '{a.get('activityName')}'")
        blob, err = safe(api.download_activity, aid)
        if err:
            print(f"   download: {err}")
            continue
        try:
            new = extract_fit(blob)
        except Exception as e:  # noqa: BLE001
            print(f"   {e}")
            continue
        local_path = DATA / "fit" / f"{aid}.fit"
        pn = fit_profile(new)
        print(f"   API file: {len(new)} bytes, {pn['records']} records, "
              f"{pn['messages'].get('lap', 0)} laps")
        if not local_path.exists():
            print("   (no archived FIT for this activity yet: showing API file only)")
            print(f"   record fields present (% of records): {pn['fields']}")
            continue
        old = local_path.read_bytes()
        same = hashlib.sha256(old).hexdigest() == hashlib.sha256(new).hexdigest()
        print(f"   archived : {len(old)} bytes -> {'IDENTICAL file' if same else 'DIFFERENT file'}")
        if same:
            continue
        po = fit_profile(old)
        diff_msgs = {k: (po['messages'].get(k, 0), pn['messages'].get(k, 0))
                     for k in set(po['messages']) | set(pn['messages'])
                     if po['messages'].get(k, 0) != pn['messages'].get(k, 0)}
        print(f"   message counts differing (archived, API): {diff_msgs or 'none'}")
        print(f"   records: archived {po['records']} / API {pn['records']}")
        fdiff = {k: (po['fields'][k], pn['fields'][k]) for k in RUN_DYNAMICS
                 if po['fields'][k] != pn['fields'][k]}
        print(f"   record field coverage differing (% archived, % API): {fdiff or 'none'}")
        sk_missing = sorted(set(po['session']) - set(pn['session']))
        print(f"   session fields missing in API file: {sk_missing or 'none'}")

    h("Done")
    print("Paste this whole output in the chat.")


if __name__ == "__main__":
    main()
