"""Exercises the MFA state machine in GarminAlarmClient with a fake
garminconnect.Garmin, since the real library isn't installed in this
lightweight test environment (and shouldn't need to be, for pure logic)."""
import sys
import types
from unittest.mock import MagicMock

import pytest

from custom_components.tado_schedule.garmin import GarminAlarmClient, GarminMfaRequired


class FakeGarmin:
    """Mimics garminconnect.Garmin just enough to drive the MFA branches."""

    instances: list["FakeGarmin"] = []

    def __init__(self, email, password, return_on_mfa=False):
        self.email = email
        self.password = password
        self.return_on_mfa = return_on_mfa
        self.client = MagicMock()
        self.login_calls = 0
        self.resume_calls = []
        self.needs_mfa_on_login = True
        FakeGarmin.instances.append(self)

    def login(self, tokenstore=None):
        self.login_calls += 1
        self.tokenstore = tokenstore
        if self.needs_mfa_on_login:
            # Real garminconnect (>=0.3.x) always returns None here - the
            # actual pending-login state lives internally on the Client
            # object, not in this tuple - so tests must not rely on a
            # truthy value to represent "MFA is pending".
            return "needs_mfa", None
        return None, "legacy-token"

    def resume_login(self, client_state, mfa_code):
        self.resume_calls.append((client_state, mfa_code))
        return None, "legacy-token"

    def get_device_alarms(self):
        return [{"alarmEnabled": True, "alarmTime": 6 * 60, "alarmDays": [1, 2, 3, 4, 5]}]


@pytest.fixture(autouse=True)
def fake_garminconnect_module(monkeypatch):
    FakeGarmin.instances = []
    module = types.ModuleType("garminconnect")
    module.Garmin = FakeGarmin
    monkeypatch.setitem(sys.modules, "garminconnect", module)
    yield
    FakeGarmin.instances = []


def test_connect_raises_mfa_required_and_remembers_state():
    client = GarminAlarmClient("a@b.com", "pw", "/tmp/tokenstore")
    with pytest.raises(GarminMfaRequired):
        client.connect()
    assert client.mfa_pending is True


def test_fetch_alarms_does_not_start_a_second_login_while_mfa_pending():
    client = GarminAlarmClient("a@b.com", "pw", "/tmp/tokenstore")
    with pytest.raises(GarminMfaRequired):
        client.connect()

    # A second fetch attempt must NOT trigger another login (that would
    # email out a second, confusing OTP) - it should just re-raise.
    with pytest.raises(GarminMfaRequired):
        client.fetch_alarms()
    assert len(FakeGarmin.instances) == 1
    assert FakeGarmin.instances[0].login_calls == 1


def test_submit_mfa_code_resumes_and_persists_session():
    client = GarminAlarmClient("a@b.com", "pw", "/tmp/tokenstore")
    with pytest.raises(GarminMfaRequired):
        client.connect()

    client.submit_mfa_code("123456")

    assert client.mfa_pending is False
    fake = FakeGarmin.instances[0]
    # The client_state passed through is whatever login() handed back
    # (None, in real garminconnect >=0.3.x) - resume_login() ignores it
    # anyway and uses the Client object's own internal pending state.
    assert fake.resume_calls == [(None, "123456")]
    fake.client.dump.assert_called_once_with("/tmp/tokenstore")


def test_fetch_alarms_works_after_mfa_resumed():
    client = GarminAlarmClient("a@b.com", "pw", "/tmp/tokenstore")
    with pytest.raises(GarminMfaRequired):
        client.connect()
    client.submit_mfa_code("123456")

    alarms = client.fetch_alarms()

    assert len(alarms) == 1
    assert alarms[0].time_of_day.hour == 6


def test_connect_succeeds_immediately_with_no_mfa_needed():
    client = GarminAlarmClient("a@b.com", "pw", "/tmp/tokenstore")
    # Simulate a valid cached tokenstore session (no MFA challenge).
    FakeGarmin.instances.clear()

    def make_no_mfa(email, password, return_on_mfa=False):
        fake = FakeGarmin(email, password, return_on_mfa)
        fake.needs_mfa_on_login = False
        return fake

    sys.modules["garminconnect"].Garmin = make_no_mfa

    client.connect()
    assert client.mfa_pending is False

    alarms = client.fetch_alarms()
    assert len(alarms) == 1


def test_submit_mfa_code_without_pending_login_raises():
    client = GarminAlarmClient("a@b.com", "pw", "/tmp/tokenstore")
    with pytest.raises(GarminMfaRequired):
        client.submit_mfa_code("000000")
