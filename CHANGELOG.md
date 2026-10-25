# Changelog

## 0.2.0 — 2026-10-25

**Data is now read through Garmin's official Connect Personal API, which is read-only.
Write access (structured workouts) is optional and requires enabling the community module.**

- New default data source: official [Garmin Connect Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api)
  via `garmin-connect-personal-api-python` (`GARMIN_PERSONAL_API_KEY`). Same original FIT files as before
  (verified byte-identical), no interactive login, no MFA.
- The unofficial python-garminconnect integration becomes an optional community module, off by default
  (`ENABLE_GARMINCONNECT=true`). It provides write access (create/schedule/delete workouts) and enriches data with
  per-lap grade-adjusted pace and shoes, which the official API does not expose.
- Workout tools explain how to enable write access when the module is off; `create_workout` still previews.
- `get_activity` shows the planned workout an activity was executed from (official API).
- `sync_status` reports read source and write access status.
- Upserts no longer erase fields the current source does not provide (e.g. VO2max).
- New `tools/probe_personal_api.py` to check the Personal API against the local archive.
- Migration from 0.1: add `GARMIN_PERSONAL_API_KEY` to `.env`; set `ENABLE_GARMINCONNECT=true` to keep
  workout tools (existing login tokens are reused); run `docker compose up -d --build`.

## 0.1.0 — 2026-09-27

First release.

- Garmin Connect → SQLite sync (history backfill + periodic incremental sync), original FIT files archived.
- MCP server (streamable HTTP, bearer token) with activity tools: `sync_garmin`, `sync_status`,
  `list_activities`, `get_activity`, `get_activity_series`, `training_summary`, `annotate_activity`, `query_sql`.
- Structured running workouts: `create_workout` (preview → confirm, calendar scheduling, in-place replace),
  `get_workout`, `list_workouts`, `delete_workout`.
- Optional personal notes for Claude in `data/athlete.md`.
- Documentation in English and Italian, third-party notices.
