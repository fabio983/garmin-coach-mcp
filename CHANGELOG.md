# Changelog

## 0.1.0 — 2026-09-27

First release.

- Garmin Connect → SQLite sync (history backfill + periodic incremental sync), original FIT files archived.
- MCP server (streamable HTTP, bearer token) with activity tools: `sync_garmin`, `sync_status`,
  `list_activities`, `get_activity`, `get_activity_series`, `training_summary`, `annotate_activity`, `query_sql`.
- Structured running workouts: `create_workout` (preview → confirm, calendar scheduling, in-place replace),
  `get_workout`, `list_workouts`, `delete_workout`.
- Optional personal notes for Claude in `data/athlete.md`.
- Documentation in English and Italian, third-party notices.
