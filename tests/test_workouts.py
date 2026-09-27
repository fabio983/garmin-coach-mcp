from app import workouts


def _steps():
    return [
        {"kind": "warmup", "time": "15:00", "hr": "120-145", "note": "easy"},
        {"repeat": 3, "steps": [
            {"kind": "interval", "distance_km": 2, "pace": "5:45-5:40"},
            {"kind": "recovery", "time": "2:00"},
        ]},
        {"kind": "cooldown", "time": "10:00"},
    ]


def test_build_structure_and_preview():
    payload, preview = workouts.build("3x2km", _steps())
    seg = payload["workoutSegments"][0]["workoutSteps"]
    assert [s["stepOrder"] for s in seg] == [1, 2, 5]
    rep = seg[1]
    assert rep["type"] == "RepeatGroupDTO" and rep["numberOfIterations"] == 3
    assert "Repeat 3 times:" in preview and "@ 5:40-5:45/km" in preview


def test_pace_target_fast_first():
    payload, _ = workouts.build("x", [{"kind": "interval", "distance_km": 1, "pace": "5:45-5:40"}])
    st = payload["workoutSegments"][0]["workoutSteps"][0]
    assert st["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert st["targetValueOne"] > st["targetValueTwo"]  # faster speed first


def test_hr_target_and_describe_roundtrip():
    payload, _ = workouts.build("x", _steps())
    text = workouts.describe({**payload, "workoutId": 1})
    assert "Warm-up 15:00 @ HR 120-145  — easy" in text
    assert "Run 2 km @ 5:40-5:45/km" in text


def test_invalid_steps():
    import pytest
    for bad in ([{"kind": "sprint", "time": "1:00"}],
                [{"kind": "interval"}],
                [{"kind": "interval", "time": "1:00", "pace": "5:00-5:10", "hr": "150-160"}]):
        with pytest.raises(workouts.WorkoutError):
            workouts.build("x", bad)
