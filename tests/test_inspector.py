"""All inputs in this module and fixtures/ are synthetic test data."""
from pathlib import Path
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from app import create_app
from engine import Inspector

FIXTURE = Path(__file__).parent / 'fixtures/success.log'
LINES = FIXTURE.read_text().splitlines()[1:]

@pytest.fixture
def success():
    inspector = Inspector(2026)
    for line in LINES:
        inspector.feed(line, clock=0)
    return inspector


def test_success(success):
    assert success.snapshot()['state'] == 'REGISTERED'
    assert success.snapshot()['registrationStatus'] == 'SUCCESS'
    assert success.events[0]['type'] == 'INITIAL_UE_MESSAGE'
    assert success.events[-1]['type'] == 'REGISTRATION_COMPLETED'
    assert success.events[-1]['rawEvidence'] == LINES[-1]
    assert success.snapshot()['networkFunctions'] == ['AMF']


def test_duration(success):
    assert success.snapshot()['durationMs'] == 538
    assert success.snapshot()['startedAt'] == '2026-09-06T15:44:57.741'


def test_suci(success):
    assert success.snapshot()['suci'] == 'suci-0-001-01-0000-0-0-0123456780'


def test_imsi_same_session(success):
    assert success.snapshot()['imsi'] == 'imsi-001010123456780'
    assert len(success.attempts) == 1
    assert {e['sessionId'] for e in success.events} == {'registration-1'}


def test_ngap(success):
    assert success.snapshot()['ranUeNgapId'] == 0
    assert success.snapshot()['amfUeNgapId'] == 1


def test_cell(success):
    assert success.snapshot()['tac'] == 7
    assert success.snapshot()['cellId'] == '0x66c000'


def test_timeout():
    i = Inspector(2026, timeout=2)
    i.feed(LINES[0], clock=0)
    i.expire(clock=1.9)
    assert i.active
    i.expire(clock=2)
    assert i.snapshot()['state'] == 'FAILED'
    assert i.events[-1]['rawEvidence'] is None
    assert i.events[-1]['timestampSource'] == 'timer'


@pytest.mark.parametrize('message', ['Registration reject', 'Registration rejected', 'Authentication failure', 'Authentication failed'])
def test_explicit_failure(message):
    i = Inspector(2026)
    line = f'09/06 15:44:58.000 [gmm] ERROR: {message}'
    i.feed(line)
    assert not i.attempts
    i.feed(LINES[0]); i.feed(line + ' (test)')
    assert i.snapshot()['state'] == 'FAILED'


def test_duplicates(success):
    count = len(success.events)
    for line in LINES:
        success.feed(line)
    assert len(success.events) == count
    assert len(success.attempts) == 1


@pytest.mark.parametrize('message', ['NF registered', 'Subscription created', 'Setup NF EndPoint', 'Open5GS daemon', 'Configuration', 'MongoDB', 'WebUI', 'PFCP associated', 'gNB-N2 accepted', 'Unrelated startup failure'])
def test_noise(message):
    i = Inspector(2026)
    i.feed(f'09/06 15:44:57.000 [amf] WARNING: {message}')
    assert i.snapshot()['state'] == 'WAITING'
    i.feed(LINES[0])
    i.feed(f'09/06 15:44:58.000 [amf] WARNING: {message}')
    assert i.snapshot()['state'] == 'UE_DETECTED'


def test_deregistration(success):
    before = success.snapshot()
    success.feed('09/06 15:45:00.000 [gmm] INFO: [imsi-999] Deregistration request')
    assert success.snapshot() == before


def test_missing_imsi():
    i = Inspector(2026)
    i.feed(LINES[0]); i.feed('09/06 15:44:58.279 [gmm] INFO: Registration complete')
    assert i.snapshot()['state'] == 'REGISTERED'
    assert i.snapshot()['imsi'] is None


@pytest.mark.parametrize('line', ['', 'garbage', '99/99 99:99:99.999 [amf] InitialUEMessage', '[other] InitialUEMessage'])
def test_malformed(line):
    i = Inspector(2026); i.feed(line)
    assert not i.attempts


def test_no_timestamp_fallback():
    i = Inspector(2026); i.feed('[amf] INFO: InitialUEMessage')
    assert i.events[0]['timestampSource'] == 'receipt'


def test_replay_timeout():
    i = Inspector(2026); i.feed(LINES[0])
    i.feed('09/06 15:45:28.000 [nrf] INFO: NF registered')
    assert i.snapshot()['state'] == 'FAILED'


def test_new_attempt(success):
    success.feed('09/06 16:00:00.000 [amf] INFO: InitialUEMessage')
    assert success.snapshot()['sessionId'] == 'registration-2'
    assert success.snapshot()['imsi'] is None


def test_api_and_ui():
    app = create_app(mode='replay', replay=FIXTURE, year=2026)
    # Feed deterministically here; actual reader is covered by subprocess replay verification.
    for line in LINES:
        app.state.inspector.feed(line)
    client = TestClient(app)
    assert client.get('/api/health').json()['matchedEvents'] == 7
    assert client.get('/api/registration').json()['durationMs'] == 538
    assert len(client.get('/api/events').json()) == 7
    assert '5G Core Inspector' in client.get('/').text
    import re
    asset = re.search(r'src="([^"]+\.js)"', client.get('/').text)[1]
    assert client.get(asset).status_code == 200


def test_ansi_evidence():
    i = Inspector(2026)
    raw = '\x1b[32m09/06 15:44:57.741\x1b[0m: [\x1b[33mamf\x1b[0m] INFO: InitialUEMessage'
    i.feed(raw)
    assert i.events[0]['rawEvidence'] == raw
    assert i.snapshot()['startedAt'] == '2026-09-06T15:44:57.741'


def test_replay_source_error(tmp_path):
    with TestClient(create_app(mode='replay', replay=tmp_path/'missing.log')) as client:
        import time
        for _ in range(100):
            health = client.get('/api/health').json()
            if health['status'] == 'error':
                break
            time.sleep(.01)
        assert health['status'] == 'error'
        assert not health['logSource']['connected']
        assert health['logSource']['error']


def test_docker_permission_error(monkeypatch):
    import asyncio
    async def denied(*args, **kwargs):
        assert args == ('sudo', '-n', 'docker', 'logs', '--follow', '--since', '0s', 'open5gs_5gc')
        assert 'shell' not in kwargs
        raise PermissionError('permission denied: docker')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', denied)
    with TestClient(create_app(mode='docker', container='open5gs_5gc')) as client:
        import time
        for _ in range(100):
            health = client.get('/api/health').json()
            if health['status'] == 'error':
                break
            time.sleep(.01)
        assert health['status'] == 'error'
        assert 'permission denied' in health['logSource']['error']


def test_deregistration_preserves_registration(success):
    before = success.snapshot()
    raw = '09/06 15:45:00.000 [gmm] INFO: [imsi-001010123456780] Deregistration request'
    success.feed(raw)
    record = success.snapshot()
    assert record['state'] == 'DEREGISTERED'
    for key in ('registrationStatus', 'startedAt', 'completedAt', 'durationMs', 'imsi', 'suci', 'sessionId'):
        assert record[key] == before[key]
    assert record['deregistrationRequestedAt'] == '2026-09-06T15:45:00.000'
    assert record['events'][-1]['type'] == 'DEREGISTRATION_REQUESTED'
    assert record['events'][-1]['rawEvidence'] == raw
    success.feed(raw)
    assert success.snapshot() == record
    success.feed('09/06 15:45:01.000 [gmm] INFO: Deregistration request')
    assert success.snapshot() == record
    success.feed('09/06 15:46:00.000 [amf] INFO: InitialUEMessage')
    assert success.snapshot()['state'] == 'UE_DETECTED'
    assert success.snapshot()['deregistrationRequestedAt'] is None
    assert len(success.attempts) == 2


def test_deregistration_without_identity(success):
    success.feed('09/06 15:45:00.000 [gmm] INFO: Deregistration request')
    assert success.snapshot()['state'] == 'DEREGISTERED'


@pytest.mark.parametrize('started', [False, True])
def test_deregistration_before_success(started):
    i = Inspector(2026)
    if started:
        i.feed(LINES[0])
    before = i.snapshot()
    i.feed('09/06 15:44:58.000 [gmm] INFO: Deregistration request')
    assert i.snapshot() == before


# Synthetic failure messages below are rule tests, not verified deployment output.
def active_after_request():
    i = Inspector(2026)
    i.feed(LINES[0], clock=0)
    i.feed('09/06 15:44:57.800 [gmm] INFO: Registration request')
    return i


def test_authentication_failure_diagnosis_and_duration():
    i = active_after_request()
    raw = '09/06 15:44:58.483 [gmm] ERROR: Authentication failure'
    i.feed(raw)
    r = i.snapshot()
    assert (r['failureStage'], r['diagnosisConfidence']) == ('AUTHENTICATION', 'EXACT')
    assert r['durationMs'] == 742
    assert r['failureEvidence']['rawLogLine'] == raw
    assert r['failureEvidence']['matchedRule'] == 'authentication_failure'
    assert r['events'][-1]['failureStage'] == 'AUTHENTICATION'
    assert r['events'][-1]['failureEvidence']['rawLogLine'] == raw


def test_security_failure_diagnosis():
    i = active_after_request()
    i.feed('09/06 15:44:58.000 [amf] ERROR: NAS MAC verification failed')
    assert (i.snapshot()['failureStage'], i.snapshot()['diagnosisConfidence']) == ('NAS_SECURITY', 'EXACT')


def test_registration_reject_extracts_actual_cause():
    i = active_after_request()
    i.feed('09/06 15:44:58.000 [gmm] ERROR: Registration reject cause: Illegal UE')
    assert i.snapshot()['failureReason'] == 'Registration rejected'
    assert i.snapshot()['protocolCause'] == 'Illegal UE'


def test_unknown_ue_by_suci_is_not_failure():
    i = active_after_request()
    i.feed('09/06 15:44:58.000 [gmm] INFO: Unknown UE by SUCI')
    assert i.snapshot()['state'] == 'REGISTRATION_IN_PROGRESS'


def test_timeout_diagnostics_by_last_observed_stage():
    i = Inspector(2026, timeout=2)
    i.feed(LINES[0], clock=0); i.expire(clock=2)
    assert (i.snapshot()['failureStage'], i.snapshot()['lastSuccessfulStage']) == ('NGAP_NAS', 'INITIAL_UE_MESSAGE')
    i = Inspector(2026, timeout=2)
    i.feed(LINES[0], clock=0)
    i.feed('09/06 15:44:57.800 [gmm] INFO: Registration request', clock=.1)
    i.expire(clock=2)
    assert (i.snapshot()['failureStage'], i.snapshot()['diagnosisConfidence']) == ('AFTER_REGISTRATION_REQUEST', 'STAGE_LEVEL')


def test_watchdog_times_out_without_new_line():
    app = create_app(mode='stdin', timeout=.05)
    with TestClient(app) as client:
        app.state.inspector.feed('[amf] INFO: InitialUEMessage')
        import time
        time.sleep(.35)
        assert client.get('/api/registration').json()['state'] == 'FAILED'


def test_no_attempt_has_no_timeout_record():
    i = Inspector(2026, timeout=.01); i.expire(clock=100)
    assert i.snapshot()['state'] == 'WAITING' and not i.events


def test_context_release_before_and_after_completion():
    i = active_after_request()
    i.feed('09/06 15:44:58.000 [amf] WARNING: UE context released')
    assert (i.snapshot()['failureStage'], i.snapshot()['diagnosisConfidence']) == ('REGISTRATION_COMPLETION', 'STAGE_LEVEL')
    success = Inspector(2026)
    for line in LINES: success.feed(line)
    before = success.snapshot()
    success.feed('09/06 15:45:00.000 [amf] WARNING: UE context released')
    assert success.snapshot() == before


def test_unrelated_generic_errors_are_ignored_during_attempt():
    i = active_after_request()
    for raw in ('09/06 15:44:58.000 [amf] ERROR: database unavailable',
                '09/06 15:44:58.001 [gmm] WARNING: unrelated failed operation'):
        i.feed(raw)
    assert i.snapshot()['state'] == 'REGISTRATION_IN_PROGRESS'


def test_repeated_failure_is_one_event():
    i = active_after_request(); raw = '09/06 15:44:58.000 [gmm] ERROR: MAC failure'
    i.feed(raw); i.feed(raw)
    assert [e['type'] for e in i.events].count('REGISTRATION_FAILED') == 1


def test_failure_for_other_identity_not_attached():
    i = active_after_request()
    i.feed('09/06 15:44:57.900 [gmm] INFO: [imsi-001010123456780] AMF_UE_NGAP_ID[1]')
    i.feed('09/06 15:44:58.000 [gmm] ERROR: [imsi-999999999999999] Authentication failure')
    assert i.snapshot()['state'] == 'REGISTRATION_IN_PROGRESS'
    assert i.uncorrelated


def test_verified_deployment_cannot_find_suci_is_exact_identification_failure():
    """Pattern captured from this Open5GS deployment on 2026-09-07."""
    i = Inspector(2026)
    i.feed('09/07 12:13:38.552 [amf] INFO: InitialUEMessage')
    i.feed('09/07 12:13:38.552 [gmm] INFO: Registration request')
    raw = ('09/07 12:13:38.555: [gmm] WARNING: '
           '[suci-0-001-01-0000-0-0-0123456781] Cannot find SUCI [404] '
           '(../src/amf/gmm-sm.c:1930)')
    i.feed(raw)
    record = i.snapshot()
    assert record['failureStage'] == 'SUBSCRIBER_IDENTIFICATION'
    assert record['failureReason'] == 'Core could not find the subscriber for the SUCI'
    assert record['diagnosisConfidence'] == 'EXACT'
    assert record['protocolCause'] == '404'
    assert record['failureEvidence']['rawLogLine'] == raw
    assert record['failureEvidence']['matchedRule'] == 'suci_not_found'
