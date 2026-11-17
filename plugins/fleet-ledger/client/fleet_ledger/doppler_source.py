"""Loads a seat's ledger credentials from Doppler at runtime.

The seat runs with a read-only Doppler service token in DOPPLER_TOKEN, scoped to its own project and
config (for example a project per seat with config prd). Nothing is cached on disk. No secret value is
ever put in an exception message, repr or log line, and errors are raised outside the `except` block, so
no exception chain keeps the request (and its Authorization header) alive.

Keys read from the config:
  FLEET_LEDGER_LOGIN        required, the seat's own login, e.g. fleet_seat_<name> (pooler form <login>.<ref> is fine)
  FLEET_LEDGER_PASSWORD     required, used exactly as stored
  FLEET_LEDGER_HOST         required
  FLEET_LEDGER_PORT         optional, default 5432
  FLEET_LEDGER_DBNAME       optional, default postgres
  FLEET_LEDGER_SSLMODE      optional, require (default), verify-ca or verify-full
  FLEET_LEDGER_SSLROOTCERT  optional, path to the server CA file; needed for verify-ca and verify-full
"""
from __future__ import annotations

import http.client
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Final, NoReturn

from .credentials_error import CredentialsError
from .seat_credentials import SeatCredentials
from .secret_value import SecretValue

TOKEN_VARIABLE: Final[str] = "DOPPLER_TOKEN"
DOWNLOAD_URL: Final[str] = "https://api.doppler.com/v3/configs/config/secrets/download?format=json"
USER_AGENT: Final[str] = "fleet-ledger-seat"
TIMEOUT_SECONDS: Final[float] = 15.0
MAX_RESPONSE_BYTES: Final[int] = 1_048_576
DEFAULT_PORT: Final[int] = 5432
MAX_PORT: Final[int] = 65535
DEFAULT_DBNAME: Final[str] = "postgres"
DEFAULT_SSLMODE: Final[str] = "require"
SSLMODES: Final[frozenset[str]] = frozenset({"require", "verify-ca", "verify-full"})
VERIFYING_SSLMODES: Final[frozenset[str]] = frozenset({"verify-ca", "verify-full"})
LOGIN_PATTERN: Final[re.Pattern[str]] = re.compile(r"fleet_seat_[a-z0-9_]+(\.[a-z0-9]+)?")
REQUIRED_KEYS: Final[tuple[str, ...]] = ("FLEET_LEDGER_LOGIN", "FLEET_LEDGER_PASSWORD", "FLEET_LEDGER_HOST")

Opener = Callable[..., Any]


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect could carry the token to another host, so none is followed."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise urllib.error.HTTPError(DOWNLOAD_URL, 310, "redirect refused", None, None)  # type: ignore[arg-type]


def default_opener() -> Opener:
    return urllib.request.build_opener(_RefuseRedirects()).open


def load_seat_credentials(environ: Mapping[str, str] | None = None, opener: Opener | None = None) -> SeatCredentials:
    """Reads DOPPLER_TOKEN from the environment and downloads the seat's config from Doppler."""
    token: str | None = (os.environ if environ is None else environ).get(TOKEN_VARIABLE)
    if not token:
        raise CredentialsError(f"{TOKEN_VARIABLE} is not set; give the seat its read-only Doppler service token")
    return parse_secrets(_download(SecretValue(token), opener or default_opener()))


def _request(token: SecretValue) -> urllib.request.Request:
    request = urllib.request.Request(DOWNLOAD_URL, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    request.add_unredirected_header("Authorization", f"Bearer {token.reveal()}")
    return request


def _download(token: SecretValue, opener: Opener) -> Mapping[str, Any]:
    failure: str | None = None
    body: bytes = b""
    try:
        with opener(_request(token), timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        failure = f"Doppler refused the request (HTTP {error.code})"
        error.close()
    except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
        failure = f"Doppler could not be reached ({type(error).__name__})"
    if failure:
        raise CredentialsError(failure)
    return _decode(body)


def _decode(body: bytes) -> Mapping[str, Any]:
    if len(body) > MAX_RESPONSE_BYTES:
        raise CredentialsError("Doppler returned a response that is too large")
    try:
        payload: Any = json.loads(body.decode("utf-8"))
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise CredentialsError("Doppler returned an unexpected response shape")
    return payload


def parse_secrets(secrets: Mapping[str, Any]) -> SeatCredentials:
    """Validates the downloaded keys. Error messages name keys, never values."""
    missing: list[str] = [key for key in REQUIRED_KEYS if not _text(secrets, key)]
    if missing:
        raise CredentialsError(f"missing Doppler keys: {', '.join(missing)}")
    login: str = _text(secrets, "FLEET_LEDGER_LOGIN")
    if not LOGIN_PATTERN.fullmatch(login):
        raise CredentialsError("FLEET_LEDGER_LOGIN is not a fleet_seat_* login")
    sslmode: str = _sslmode(secrets)
    return SeatCredentials(
        login=login, password=SecretValue(secrets["FLEET_LEDGER_PASSWORD"]),
        host=_text(secrets, "FLEET_LEDGER_HOST"), port=_port(secrets),
        dbname=_text(secrets, "FLEET_LEDGER_DBNAME") or DEFAULT_DBNAME, sslmode=sslmode,
        sslrootcert=_text(secrets, "FLEET_LEDGER_SSLROOTCERT") or None,
    )


def _sslmode(secrets: Mapping[str, Any]) -> str:
    sslmode: str = _text(secrets, "FLEET_LEDGER_SSLMODE") or DEFAULT_SSLMODE
    if sslmode not in SSLMODES:
        raise CredentialsError(f"FLEET_LEDGER_SSLMODE must be one of {', '.join(sorted(SSLMODES))}")
    if sslmode in VERIFYING_SSLMODES and not _text(secrets, "FLEET_LEDGER_SSLROOTCERT"):
        raise CredentialsError(f"FLEET_LEDGER_SSLMODE {sslmode} needs FLEET_LEDGER_SSLROOTCERT")
    return sslmode


def _text(secrets: Mapping[str, Any], key: str) -> str:
    value: Any = secrets.get(key)
    return value.strip() if isinstance(value, str) else ""


def _port(secrets: Mapping[str, Any]) -> int:
    raw: str = _text(secrets, "FLEET_LEDGER_PORT")
    if not raw:
        return DEFAULT_PORT
    if not (raw.isascii() and raw.isdecimal()) or not 0 < int(raw) <= MAX_PORT:
        raise CredentialsError("FLEET_LEDGER_PORT is not a valid port")
    return int(raw)
