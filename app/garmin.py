"""Garmin Connect login via python-garminconnect (tokens persisted in DATA_DIR/tokens)."""
from __future__ import annotations

import getpass
import logging

from garminconnect import Garmin

from . import config

log = logging.getLogger(__name__)

RELOGIN_HINT = "Log in again with: docker compose run --rm garmin-coach login"


class AuthRequired(RuntimeError):
    pass


def _tokenstore() -> str:
    config.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    return str(config.TOKEN_DIR)


def client() -> Garmin:
    """Authenticated client from saved tokens (refreshed automatically).
    Raises AuthRequired when tokens are no longer valid and no usable credentials exist."""
    g = Garmin(config.GARMIN_EMAIL, config.GARMIN_PASSWORD,
               prompt_mfa=_no_mfa, retry_attempts=3)
    try:
        g.login(_tokenstore())
    except Exception as e:  # noqa: BLE001
        raise AuthRequired(f"Garmin login failed ({type(e).__name__}: {e}). {RELOGIN_HINT}") from e
    return g


def persist(g: Garmin) -> None:
    """Save tokens (they may have been refreshed during the calls)."""
    try:
        g.client.dump(_tokenstore())
    except Exception as e:  # noqa: BLE001
        log.warning("Could not save tokens: %s", e)


def _no_mfa() -> str:
    raise AuthRequired("Garmin is asking for an MFA code: an interactive login is required.")


def interactive_login() -> None:
    email = config.GARMIN_EMAIL or input("Garmin email: ").strip()
    password = config.GARMIN_PASSWORD or getpass.getpass("Garmin password: ")
    g = Garmin(email, password, prompt_mfa=lambda: input("MFA code: ").strip())
    g.login(_tokenstore())
    persist(g)
    name = None
    try:
        name = g.get_full_name()
    except Exception:  # noqa: BLE001
        pass
    print(f"Login OK{f' ({name})' if name else ''}. Tokens saved in {config.TOKEN_DIR}")
