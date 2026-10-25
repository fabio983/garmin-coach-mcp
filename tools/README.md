# Tools

## probe_personal_api.py

Read-only check of the official [Garmin Connect Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api)
against your local archive: authentication, activity search and history depth, available endpoints,
and a comparison between the original files returned by the API and the FIT files already in `data/fit/`.

1. Create a Personal API key in Garmin Connect (Settings → Personal API) and add it to `.env`:

   ```
   GARMIN_PERSONAL_API_KEY=...
   ```

2. From the repository folder run a one-off container (it does not touch the running service,
   and mounts `data/` read-only):

   ```bash
   docker run --rm --env-file .env \
     -v "$PWD/data:/data:ro" -v "$PWD:/repo:ro" \
     python:3.12-slim sh -c \
     "pip install -q --root-user-action=ignore garmin-connect-personal-api-python==1.0.0 fitdecode==0.11.0 \
      && python -I /repo/tools/probe_personal_api.py"
   ```

   Options: `--runs N` (recent runs to compare, default 3), `--max-pages N` (search pages of 100 for the
   history check, default 30).

The output contains no secrets.
