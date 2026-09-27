"""SQLite schema and connections."""
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id     INTEGER PRIMARY KEY,
    start_local     TEXT,       -- 'YYYY-MM-DD HH:MM:SS' local time
    start_gmt       TEXT,
    name            TEXT,
    type_key        TEXT,       -- running, treadmill_running, trail_running, strength_training, ...
    distance_m      REAL,
    duration_s      REAL,       -- timer time
    moving_s        REAL,
    elapsed_s       REAL,
    avg_speed       REAL,       -- m/s
    avg_hr          REAL,
    max_hr          REAL,
    avg_cadence     REAL,       -- steps/min
    avg_power       REAL,
    elev_gain       REAL,
    elev_loss       REAL,
    calories        REAL,
    aerobic_te      REAL,
    anaerobic_te    REAL,
    training_load   REAL,
    vo2max          REAL,
    avg_gct_ms      REAL,
    avg_vo_cm       REAL,
    avg_vratio      REAL,
    avg_stride_m    REAL,
    gear            TEXT,       -- shoes assigned in Garmin Connect (if any)
    has_details     INTEGER DEFAULT 0, -- 1 ok, 0 pending, -1 download failed
    fit_path        TEXT,
    raw_json        TEXT,       -- full Garmin summary JSON (use json_extract for extra fields)
    synced_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_act_start ON activities(start_local);
CREATE INDEX IF NOT EXISTS ix_act_type ON activities(type_key);

CREATE TABLE IF NOT EXISTS laps (
    activity_id     INTEGER,
    lap_index       INTEGER,    -- 1..N
    start_time      TEXT,       -- UTC ISO
    start_offset_s  REAL,       -- seconds from activity start
    trigger         TEXT,       -- manual, distance, time, session_end, ...
    intensity       TEXT,       -- active, rest, warmup, cooldown (structured workouts)
    elapsed_s       REAL,
    timer_s         REAL,
    distance_m      REAL,
    avg_speed       REAL,       -- m/s
    max_speed       REAL,
    gap_speed       REAL,       -- m/s grade adjusted (from Garmin API, if available)
    avg_hr          REAL,
    max_hr          REAL,
    avg_cadence     REAL,       -- steps/min
    max_cadence     REAL,
    avg_power       REAL,
    max_power       REAL,
    gct_ms          REAL,
    gct_bal_left    REAL,       -- % left ground contact time (FIT stance_time_balance)
    vo_cm           REAL,
    vratio          REAL,       -- %
    step_len_m      REAL,
    ascent_m        REAL,
    descent_m       REAL,
    calories        REAL,
    avg_temp        REAL,       -- watch sensor: usually unreliable
    PRIMARY KEY (activity_id, lap_index)
);

CREATE TABLE IF NOT EXISTS records (
    activity_id     INTEGER,
    t_s             INTEGER,    -- seconds from start (relative timestamp, pauses included)
    distance_m      REAL,
    speed           REAL,       -- m/s
    hr              INTEGER,
    cadence         REAL,       -- steps/min
    altitude        REAL,
    power           REAL,
    gct_ms          REAL,
    gct_bal_left    REAL,
    vo_cm           REAL,
    vratio          REAL,
    step_len_m      REAL,
    temp            REAL,
    lat             REAL,
    lon             REAL,
    PRIMARY KEY (activity_id, t_s)
) WITHOUT ROWID;

-- Data Garmin lacks or gets wrong: written by Claude on the athlete's request
CREATE TABLE IF NOT EXISTS annotations (
    activity_id     INTEGER PRIMARY KEY,
    real_temp_c     REAL,
    humidity_pct    REAL,
    treadmill       INTEGER,    -- 1 = treadmill (overrides Garmin type)
    shoe            TEXT,
    session_type    TEXT,       -- easy, long, tempo, threshold, intervals, race, test...
    rpe             REAL,
    hrr_60          REAL,       -- manual 60" heart rate recovery
    notes           TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT,
    finished_at     TEXT,
    mode            TEXT,
    new_activities  INTEGER,
    detailed        INTEGER,
    status          TEXT,
    message         TEXT
);
"""


def connect(readonly: bool = False) -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if readonly:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=30,
                               check_same_thread=False)
        conn.execute("PRAGMA query_only = ON")
    else:
        conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
