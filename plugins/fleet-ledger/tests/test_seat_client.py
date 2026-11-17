"""Tests for the seat-side runtime that need no database: Doppler loading, secret masking, connection setup,
background heartbeats."""
from __future__ import annotations

import io
import json
import pickle
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Self
from uuid import uuid4

import pytest
from fleet_ledger import (
    ClaimedTask,
    CredentialsError,
    HeartbeatKeeper,
    LeaseLostError,
    SeatCredentials,
    SecretValue,
    load_seat_credentials,
)
from fleet_ledger.__main__ import EXIT_FAILED, EXIT_USAGE, main
from fleet_ledger.doppler_source import default_opener
from fleet_ledger.seat_connection import connect_seat

FAKE_TOKEN: str = "dp.st.prd.fake-token-for-tests"
FAKE_PASSWORD: str = "fake-password-for-tests-0123456789"
LOGIN: str = "fleet_seat_example"
GOOD_SECRETS: dict[str, str] = {
    "FLEET_LEDGER_LOGIN": LOGIN,
    "FLEET_LEDGER_PASSWORD": FAKE_PASSWORD,
    "FLEET_LEDGER_HOST": "db.example.test",
}
DOPPLER_HOST: str = "api.doppler.com"
SHORT_LEASE: timedelta = timedelta(milliseconds=300)
FAST_BEAT: timedelta = timedelta(milliseconds=50)
QUICK_STOP: timedelta = timedelta(milliseconds=200)
SETTLE_SECONDS: float = 0.6


class FakeResponse(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _opener(payload: Any, seen: list[Any]) -> Any:
    def open_request(request: Any, timeout: float) -> FakeResponse:
        seen.append(request)
        return FakeResponse(json.dumps(payload).encode("utf-8"))
    return open_request


def _failing_opener(error: Exception) -> Any:
    def open_request(request: Any, timeout: float) -> FakeResponse:
        raise error
    return open_request


def _credentials(sslmode: str = "require") -> SeatCredentials:
    return SeatCredentials(LOGIN, SecretValue(FAKE_PASSWORD), "db.example.test", 6543, "postgres", sslmode)


def _leaks(error: BaseException, secret: str) -> bool:
    """True when the secret shows anywhere a crash reporter would look: message, chain or formatted traceback."""
    text: str = "".join(traceback.format_exception(error))
    return secret in text or error.__context__ is not None or error.__cause__ is not None


def _task() -> ClaimedTask:
    return ClaimedTask(uuid4(), 1, datetime.now(timezone.utc), "t", "done", "t0", (), None, {})


class FakeClient:
    """Stands in for LedgerClient; `behaviour` decides what each heartbeat does."""

    def __init__(self, behaviour: Any) -> None:
        self.behaviour = behaviour
        self.calls: int = 0

    def heartbeat(self, task: ClaimedTask, lease: timedelta) -> datetime:
        self.calls += 1
        return self.behaviour()


def test_secret_value_never_prints_itself() -> None:
    secret = SecretValue(FAKE_PASSWORD)
    shown: list[str] = [repr(secret), str(secret), f"{secret}", f"{secret!r}", repr(_credentials())]
    assert all(FAKE_PASSWORD not in text for text in shown)
    assert secret.reveal() == FAKE_PASSWORD
    with pytest.raises(TypeError):
        pickle.dumps(secret)
    with pytest.raises(ValueError):
        SecretValue("")


def test_loads_credentials_from_doppler_with_the_seat_token() -> None:
    seen: list[Any] = []
    creds = load_seat_credentials({"DOPPLER_TOKEN": FAKE_TOKEN}, _opener(GOOD_SECRETS, seen))
    assert (creds.login, creds.host, creds.port, creds.dbname, creds.sslmode) == (
        LOGIN, "db.example.test", 5432, "postgres", "require")
    assert creds.password.reveal() == FAKE_PASSWORD
    request = seen[0]
    assert request.host == DOPPLER_HOST and request.full_url.startswith("https://")
    assert request.get_method() == "GET"
    assert request.unredirected_hdrs.get("Authorization") == f"Bearer {FAKE_TOKEN}"
    assert "Authorization" not in request.headers


def test_optional_keys_and_pooler_login_are_read() -> None:
    secrets = {**GOOD_SECRETS, "FLEET_LEDGER_LOGIN": f"{LOGIN}.abcdefghijk", "FLEET_LEDGER_PORT": "6543",
               "FLEET_LEDGER_DBNAME": "ledger", "FLEET_LEDGER_SSLMODE": "verify-full",
               "FLEET_LEDGER_SSLROOTCERT": "/etc/ssl/ledger-ca.crt"}
    creds = load_seat_credentials({"DOPPLER_TOKEN": FAKE_TOKEN}, _opener(secrets, []))
    assert (creds.login, creds.port, creds.dbname, creds.sslmode, creds.sslrootcert) == (
        f"{LOGIN}.abcdefghijk", 6543, "ledger", "verify-full", "/etc/ssl/ledger-ca.crt")


def test_password_is_used_exactly_as_stored() -> None:
    padded: str = f" {FAKE_PASSWORD} "
    creds = load_seat_credentials({"DOPPLER_TOKEN": FAKE_TOKEN},
                                  _opener({**GOOD_SECRETS, "FLEET_LEDGER_PASSWORD": padded}, []))
    assert creds.password.reveal() == padded


def test_missing_token_is_refused_before_any_request() -> None:
    seen: list[Any] = []
    with pytest.raises(CredentialsError, match="DOPPLER_TOKEN is not set"):
        load_seat_credentials({}, _opener(GOOD_SECRETS, seen))
    assert seen == []


@pytest.mark.parametrize("change, message", [
    ({"FLEET_LEDGER_PASSWORD": ""}, "missing Doppler keys: FLEET_LEDGER_PASSWORD"),
    ({"FLEET_LEDGER_LOGIN": "postgres"}, "not a fleet_seat"),
    ({"FLEET_LEDGER_SSLMODE": "disable"}, "FLEET_LEDGER_SSLMODE must be"),
    ({"FLEET_LEDGER_SSLMODE": "verify-full"}, "needs FLEET_LEDGER_SSLROOTCERT"),
    ({"FLEET_LEDGER_PORT": "99999"}, "not a valid port"),
    ({"FLEET_LEDGER_PORT": "5²"}, "not a valid port"),
])
def test_bad_config_names_the_key_never_the_value(change: dict[str, str], message: str) -> None:
    with pytest.raises(CredentialsError, match=message) as caught:
        load_seat_credentials({"DOPPLER_TOKEN": FAKE_TOKEN}, _opener({**GOOD_SECRETS, **change}, []))
    assert not _leaks(caught.value, FAKE_PASSWORD) and not _leaks(caught.value, FAKE_TOKEN)


@pytest.mark.parametrize("error, message", [
    (urllib.error.HTTPError("https://x", 401, f"bad token {FAKE_TOKEN}", None, None), r"HTTP 401"),
    (urllib.error.URLError(f"no route {FAKE_TOKEN}"), "could not be reached"),
    (TimeoutError(FAKE_TOKEN), "could not be reached"),
])
def test_doppler_failures_leave_no_trace_of_the_token(error: Exception, message: str) -> None:
    with pytest.raises(CredentialsError, match=message) as caught:
        load_seat_credentials({"DOPPLER_TOKEN": FAKE_TOKEN}, _failing_opener(error))
    assert not _leaks(caught.value, FAKE_TOKEN)


@pytest.mark.parametrize("payload", [["not", "a", "dict"], "x" * 2_000_000])
def test_odd_responses_are_refused(payload: Any) -> None:
    with pytest.raises(CredentialsError):
        load_seat_credentials({"DOPPLER_TOKEN": FAKE_TOKEN}, _opener(payload, []))


def test_default_opener_refuses_redirects() -> None:
    handlers = [h for h in urllib.request.build_opener().handlers]
    opener_handlers = default_opener().__self__.handlers
    refusing = [h for h in opener_handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert len(refusing) == 1 and type(refusing[0]) is not urllib.request.HTTPRedirectHandler
    with pytest.raises(urllib.error.HTTPError):
        refusing[0].redirect_request(None, None, 302, "Found", {}, "http://elsewhere.test/")
    assert handlers  # the stock opener still has its own redirect handler


def test_connect_passes_password_only_to_the_driver_in_autocommit() -> None:
    calls: list[dict[str, Any]] = []
    marker: object = object()

    def connector(**kwargs: Any) -> object:
        calls.append(kwargs)
        return marker

    assert connect_seat(_credentials(), connector) is marker
    kwargs = calls[0]
    assert kwargs["password"] == FAKE_PASSWORD and kwargs["user"] == LOGIN
    assert kwargs["autocommit"] is True and kwargs["sslmode"] == "require" and kwargs["port"] == 6543
    assert kwargs["keepalives"] == 1 and kwargs["tcp_user_timeout"] > 0 and "sslrootcert" not in kwargs


def test_connect_failure_leaves_no_trace_of_the_password() -> None:
    def connector(**kwargs: Any) -> object:
        raise RuntimeError(f"auth failed for password {kwargs['password']}")

    with pytest.raises(CredentialsError, match=f"could not connect as {LOGIN} \\(RuntimeError\\)") as caught:
        connect_seat(_credentials(), connector)
    assert not _leaks(caught.value, FAKE_PASSWORD)


def test_keeper_renews_until_stopped() -> None:
    client = FakeClient(lambda: datetime.now(timezone.utc))
    with HeartbeatKeeper(client, _task(), threading.Lock(), timedelta(minutes=5), FAST_BEAT) as beat:
        time.sleep(SETTLE_SECONDS / 2)
    assert beat.renewals >= 1 and beat.stopped and not beat.lost


def test_keeper_marks_lost_when_the_ledger_says_so() -> None:
    def lost() -> datetime:
        raise LeaseLostError("lease lost")

    client = FakeClient(lost)
    with HeartbeatKeeper(client, _task(), threading.Lock(), timedelta(minutes=5), FAST_BEAT) as beat:
        time.sleep(SETTLE_SECONDS / 2)
    assert beat.lost and client.calls == 1


def test_keeper_marks_lost_after_a_whole_lease_of_failures() -> None:
    def broken() -> datetime:
        raise ConnectionError("network down")

    with HeartbeatKeeper(FakeClient(broken), _task(), threading.Lock(), SHORT_LEASE, FAST_BEAT) as beat:
        time.sleep(SETTLE_SECONDS)
    assert beat.lost and beat.failures >= 2 and beat.last_error == "ConnectionError"


def test_keeper_stop_is_bounded_when_a_heartbeat_hangs() -> None:
    release = threading.Event()
    client = FakeClient(lambda: release.wait(5))
    started: float = time.monotonic()
    with HeartbeatKeeper(client, _task(), threading.Lock(), timedelta(minutes=5), FAST_BEAT, QUICK_STOP) as beat:
        time.sleep(FAST_BEAT.total_seconds() * 3)
    took: float = time.monotonic() - started
    release.set()
    assert took < 2 and not beat.stopped


def test_cli_rejects_unknown_command_and_reports_missing_token(monkeypatch: pytest.MonkeyPatch,
                                                              capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("DOPPLER_TOKEN", raising=False)
    assert main(["claim"]) == EXIT_USAGE
    assert main(["check"]) == EXIT_FAILED
    assert "DOPPLER_TOKEN is not set" in capsys.readouterr().err
