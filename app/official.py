"""Official Garmin Connect Personal API (read-only), via Garmin's garmin-connect-personal-api-python.

The API key (GARMIN_PERSONAL_API_KEY) is exchanged for a 24 h bearer token, cached in DATA_DIR/tokens
and renewed automatically. The key itself expires (30 days to 1 year, chosen when it is created).
"""
from __future__ import annotations

import logging
import time
from typing import Iterator

from garmin_personal_api import (GarminPersonalApiClient, GarminPersonalApiError, HttpError,
                                 PersonalApiAuthenticator)

from . import config

log = logging.getLogger(__name__)

KEY_HINT = ("Create a new Personal API key in Garmin Connect (Settings → Personal API), put it in "
            "GARMIN_PERSONAL_API_KEY in .env and run `docker compose up -d`.")


class AuthError(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


def _wrap(e: Exception) -> Exception:
    if isinstance(e, HttpError) and e.status_code in (401, 403):
        return AuthError(f"Personal API rejected the key or token (HTTP {e.status_code}): the key may be "
                         f"expired or revoked. {KEY_HINT}")
    if isinstance(e, HttpError) and e.status_code == 429:
        return RateLimited("Personal API rate limit reached (HTTP 429): try again later.")
    return e


class Client:
    """Thin wrapper with token handling and the few calls garmin-coach needs."""

    def __init__(self):
        if not config.GARMIN_PERSONAL_API_KEY:
            raise AuthError(f"GARMIN_PERSONAL_API_KEY is not set. {KEY_HINT}")
        config.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        self._auth = PersonalApiAuthenticator(bearer_token_cache_file=config.PERSONAL_API_TOKEN_CACHE)
        self._token = None
        self._api: GarminPersonalApiClient | None = None
        self._ensure_token()

    def _ensure_token(self, force: bool = False):
        if force or self._token is None or self._token.expires_at - time.time() < 600:
            try:
                self._token = self._auth.obtain_token(config.GARMIN_PERSONAL_API_KEY, force_refresh=force)
            except (HttpError, GarminPersonalApiError) as e:
                raise _wrap(e) from e
            if self._api is None:
                self._api = GarminPersonalApiClient(self._token.access_token)
            else:
                self._api.update_bearer_token(self._token.access_token)

    def _call(self, fn, *args, **kwargs):
        self._ensure_token()
        try:
            return fn(self._api, *args, **kwargs)
        except HttpError as e:
            if e.status_code == 401:  # token revoked early: retry once with a fresh one
                self._ensure_token(force=True)
                try:
                    return fn(self._api, *args, **kwargs)
                except (HttpError, GarminPersonalApiError) as e2:
                    raise _wrap(e2) from e2
            raise _wrap(e) from e

    def activities_since(self, start_date: str, page_size: int = 100) -> Iterator[dict]:
        """Yield activity summaries, newest first, down to start_date (YYYY-MM-DD, inclusive)."""
        start = 0
        while True:
            res = self._call(GarminPersonalApiClient.search_activities, start=start, limit=page_size)
            items = res if isinstance(res, list) else (res or {}).get("activityList") or []
            if not items:
                return
            for a in items:
                if (a.get("startTimeLocal") or "")[:10] < start_date:
                    return
                yield a
            if len(items) < page_size:
                return
            start += page_size
            time.sleep(config.REQUEST_DELAY_S)

    def download_activity(self, activity_id) -> bytes:
        """Original activity file (zip containing the FIT)."""
        return self._call(GarminPersonalApiClient.download_activity, activity_id)

    def activity_workouts(self, activity_id) -> list:
        """Planned workout(s) the activity was executed from (empty list if none)."""
        try:
            res = self._call(GarminPersonalApiClient.get_activity_workouts, activity_id)
        except HttpError as e:
            if e.status_code == 404:
                return []
            raise
        return res if isinstance(res, list) else []

    def close(self):
        if self._api:
            self._api.close()
        self._auth.close()
