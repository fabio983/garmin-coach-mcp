"""Build Garmin structured running workouts (workout-service JSON) from a simple step list.

Step format (JSON list):
  {"kind": "warmup", "time": "15:00", "hr": "120-145", "note": "easy"}
  {"repeat": 3, "steps": [
      {"kind": "interval", "distance_km": 2, "pace": "5:40-5:45"},
      {"kind": "recovery", "time": "2:00"}
  ]}
  {"kind": "cooldown", "time": "10:00"}

kind: warmup | interval | recovery | rest | cooldown | other
duration (exactly one): time "mm:ss" or "h:mm:ss" | seconds | distance_km | distance_m | lap (until lap button)
target (optional, at most one): pace "m:ss-m:ss" (per km) | hr "min-max" (bpm)
note: short text shown on the watch for that step
"""
from __future__ import annotations

import re

STEP_TYPES = {
    "warmup": (1, "warmup"),
    "cooldown": (2, "cooldown"),
    "interval": (3, "interval"),
    "recovery": (4, "recovery"),
    "rest": (5, "rest"),
    "other": (7, "other"),
}
KIND_LABEL = {"warmup": "Warm-up", "cooldown": "Cool-down", "interval": "Run",
              "recovery": "Recovery", "rest": "Rest", "other": "Other"}

NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
PACE_TARGET = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}
HR_TARGET = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}

DEFAULT_PACE_S = 390  # 6:30/km, used to estimate distance steps without a pace target


class WorkoutError(ValueError):
    pass


def _clock_to_s(txt: str) -> int:
    parts = [int(p) for p in str(txt).strip().split(":")]
    if len(parts) == 1:
        return parts[0] * 60  # "15" = 15 minutes
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def _fmt_clock(s: float) -> str:
    s = int(round(s))
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _range(txt: str) -> tuple[str, str]:
    m = re.fullmatch(r"\s*([\d:]+)\s*[-–/]\s*([\d:]+)\s*", str(txt))
    if not m:
        raise WorkoutError(f"invalid range: {txt!r} (expected 'a-b')")
    return m.group(1), m.group(2)


def _pace_target(txt: str) -> tuple[dict, float, str]:
    a, b = _range(txt)
    sa, sb = _clock_to_s(a) if ":" in a else int(a), _clock_to_s(b) if ":" in b else int(b)
    slow, fast = max(sa, sb), min(sa, sb)
    # Same order the Garmin Connect editor uses:
    # targetValueOne = faster speed (m/s), targetValueTwo = slower speed.
    t = {"targetType": PACE_TARGET, "targetValueOne": round(1000 / fast, 4),
         "targetValueTwo": round(1000 / slow, 4)}
    return t, (slow + fast) / 2, f"@ {_fmt_clock(fast)}-{_fmt_clock(slow)}/km"


def _hr_target(txt: str) -> tuple[dict, str]:
    a, b = _range(txt)
    lo, hi = sorted((int(a), int(b)))
    return {"targetType": HR_TARGET, "targetValueOne": lo, "targetValueTwo": hi}, f"@ HR {lo}-{hi}"


class _Builder:
    def __init__(self):
        self.order = 0
        self.lines: list[str] = []

    def step(self, spec: dict, indent: str) -> tuple[dict, float]:
        kind = (spec.get("kind") or "interval").lower()
        if kind not in STEP_TYPES:
            raise WorkoutError(f"invalid kind: {kind!r}")
        self.order += 1
        tid, tkey = STEP_TYPES[kind]
        out: dict = {
            "type": "ExecutableStepDTO",
            "stepOrder": self.order,
            "stepType": {"stepTypeId": tid, "stepTypeKey": tkey, "displayOrder": tid},
        }

        target, pace_s, tdesc = {"targetType": NO_TARGET}, None, ""
        if spec.get("pace") and spec.get("hr"):
            raise WorkoutError("a step can have only one target (pace or hr)")
        if spec.get("pace"):
            target, pace_s, tdesc = _pace_target(spec["pace"])
        elif spec.get("hr"):
            target, tdesc = _hr_target(spec["hr"])
        out.update(target)

        if spec.get("time") or spec.get("seconds"):
            secs = _clock_to_s(spec["time"]) if spec.get("time") else int(spec["seconds"])
            out["endCondition"] = {"conditionTypeId": 2, "conditionTypeKey": "time",
                                   "displayOrder": 2, "displayable": True}
            out["endConditionValue"] = float(secs)
            est, ddesc = secs, _fmt_clock(secs)
        elif spec.get("distance_km") or spec.get("distance_m"):
            meters = float(spec["distance_m"]) if spec.get("distance_m") else float(spec["distance_km"]) * 1000
            out["endCondition"] = {"conditionTypeId": 3, "conditionTypeKey": "distance",
                                   "displayOrder": 3, "displayable": True}
            out["endConditionValue"] = meters
            out["preferredEndConditionUnit"] = {"unitKey": "kilometer"}
            est = meters / 1000 * (pace_s or DEFAULT_PACE_S)
            ddesc = f"{meters / 1000:g} km"
        elif spec.get("lap"):
            out["endCondition"] = {"conditionTypeId": 1, "conditionTypeKey": "lap.button",
                                   "displayOrder": 1, "displayable": True}
            est, ddesc = 0, "until lap button"
        else:
            raise WorkoutError(f"step without a duration: {spec}")

        if spec.get("note"):
            out["description"] = str(spec["note"])[:100]
        self.lines.append(f"{indent}{KIND_LABEL[kind]} {ddesc} {tdesc}".rstrip()
                          + (f"  — {spec['note']}" if spec.get("note") else ""))
        return out, est

    def steps(self, specs: list, indent: str = "") -> tuple[list, float]:
        res, total = [], 0.0
        for spec in specs:
            if "repeat" in spec:
                n = int(spec["repeat"])
                if n < 1 or not spec.get("steps"):
                    raise WorkoutError("repeat needs a number >= 1 and a 'steps' list")
                self.order += 1
                grp = {
                    "type": "RepeatGroupDTO",
                    "stepOrder": self.order,
                    "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                    "numberOfIterations": n,
                    "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations",
                                     "displayOrder": 7, "displayable": False},
                    "endConditionValue": float(n),
                    "smartRepeat": False,
                }
                self.lines.append(f"{indent}Repeat {n} times:")
                children, est = self.steps(spec["steps"], indent + "   ")
                grp["workoutSteps"] = children
                res.append(grp)
                total += est * n
            else:
                st, est = self.step(spec, indent)
                res.append(st)
                total += est
        return res, total


def build(name: str, steps: list, description: str | None = None) -> tuple[dict, str]:
    """Return (Garmin JSON payload, text preview)."""
    if not steps:
        raise WorkoutError("no steps")
    b = _Builder()
    wsteps, est = b.steps(steps)
    sport = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
    payload = {
        "workoutName": name[:80],
        "sportType": sport,
        "estimatedDurationInSecs": int(est),
        "workoutSegments": [{"segmentOrder": 1, "sportType": sport, "workoutSteps": wsteps}],
    }
    if description:
        payload["description"] = description[:1000]
    preview = "\n".join([f"{name}  (estimated ~{_fmt_clock(est)})"] + b.lines)
    return payload, preview


def describe(w: dict) -> str:
    """Readable view of a Garmin workout (JSON from get_workout_by_id)."""
    lines = [f"{w.get('workoutName')}  (id {w.get('workoutId')}, "
             f"estimated ~{_fmt_clock(w.get('estimatedDurationInSecs') or 0)})"]

    def pace_str(mps):
        return _fmt_clock(1000 / mps) if mps else "?"

    def num(x):
        return int(x) if isinstance(x, float) and x.is_integer() else x

    def walk(steps, indent=""):
        for st in sorted(steps or [], key=lambda x: x.get("stepOrder") or 0):
            key = (st.get("stepType") or {}).get("stepTypeKey")
            if st.get("type") == "RepeatGroupDTO" or key == "repeat":
                lines.append(f"{indent}Repeat {st.get('numberOfIterations')} times:")
                walk(st.get("workoutSteps"), indent + "   ")
                continue
            cond = (st.get("endCondition") or {}).get("conditionTypeKey")
            v = st.get("endConditionValue")
            dur = {"time": lambda: _fmt_clock(v or 0), "distance": lambda: f"{(v or 0) / 1000:g} km",
                   "lap.button": lambda: "until lap button"}.get(cond, lambda: f"{cond} {v}")()
            tkey = (st.get("targetType") or {}).get("workoutTargetTypeKey")
            a, b = st.get("targetValueOne"), st.get("targetValueTwo")
            tgt = ""
            if tkey == "pace.zone":
                tgt = f"@ {pace_str(a)}-{pace_str(b)}/km"
            elif tkey == "heart.rate.zone":
                tgt = f"@ HR {num(a)}-{num(b)}" if a else f"@ HR zone {st.get('zoneNumber')}"
            elif tkey and tkey != "no.target":
                tgt = f"@ {tkey} {a}-{b}"
            note = f"  — {st['description']}" if st.get("description") else ""
            lines.append(f"{indent}{KIND_LABEL.get(key, key)} {dur} {tgt}".rstrip() + note)

    for seg in w.get("workoutSegments") or []:
        walk(seg.get("workoutSteps"))
    return "\n".join(lines)
