"""Synthetic, source-derived OAI v2.2.2 cases. No captured subscriber logs."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from engine import Inspector

FIXTURE = Path(__file__).parent / 'fixtures/oai-success.log'
REQUEST = 'Received Registration Request message, handling...'
COMPLETE = '5GMM state transition: COMM-PROC-INIT -> 5GMM-REGISTERED (event: [REGISTRATION_COMPLETE_RECEIVED])'


def log(message, ms=0, component='amf_n1'):
    return f'[2026-10-04 12:00:00.{ms:03d}] [{component}] [debug] {message}'


def active():
    engine = Inspector(year=1999)
    engine.feed(log(REQUEST), clock=0)
    engine.feed(log('Received IMSI 001010123456780', 1))
    return engine


def replay():
    engine = Inspector()
    for line in FIXTURE.read_text().splitlines():
        engine.feed(line)
    engine.finish()
    return engine


def test_detect_from_format_not_container_name():
    engine = Inspector()
    engine.feed('oai-core | 10/04 12:00:00.000 [amf] INFO: InitialUEMessage')
    assert engine.detection()['core'] == 'open5gs'
    assert engine.snapshot()['core'] == 'open5gs'
    other = Inspector()
    other.feed('open5gs | ' + log(REQUEST))
    assert other.detection()['core'] == 'oai'
    assert other.snapshot()['core'] == 'oai'
    assert other.detection()['adapterTarget'] == 'v2.2.2'


def test_noise_and_vendor_names_do_not_select_adapter():
    engine = Inspector()
    for raw in ('oai-amf started', 'Open5GS connected', '[NAS] Registration complete',
                log('Registration complete', component='nas_mm'),
                '[amf] [debug] Registration complete'):
        engine.feed(raw)
    assert engine.detection()['status'] == 'waiting'
    assert not engine.attempts


def test_embedded_open5gs_example_is_not_a_second_signature():
    engine = active()
    engine.feed(log('Example format [amf] INFO: InitialUEMessage', 2, 'amf_app'))
    assert engine.detection()['core'] == 'oai'
    assert len(engine.attempts) == 1


@pytest.mark.parametrize('first', ['oai', 'open5gs'])
def test_mixed_stream_preserves_history_and_pauses_timeouts(first):
    engine = Inspector(timeout=1)
    oai = log(REQUEST)
    open5gs = '10/04 12:00:00.000 [amf] INFO: InitialUEMessage'
    engine.feed(oai if first == 'oai' else open5gs, clock=0)
    before = engine.snapshot()
    engine.feed(open5gs if first == 'oai' else oai)
    engine.feed(log(COMPLETE, 100))
    engine.expire(clock=100)
    engine.finish()
    assert engine.snapshot() == before
    assert engine.detection()['status'] == 'mixed'
    assert engine.detection()['core'] is None
    assert engine.detection()['observedCores'] == ['oai', 'open5gs']
    assert engine.uncorrelated


def test_source_derived_success_and_pdu_at_eof():
    engine = replay()
    record = engine.snapshot()
    assert record['core'] == 'oai'
    assert record['state'] == 'REGISTERED'
    assert record['durationMs'] == 200  # Starts at observed NAS request, not generic Initial UE.
    assert record['startedAt'] == '2026-10-04T12:00:00.010'
    assert record['imsi'] == 'imsi-001010123456780'
    assert record['amfUeNgapId'] == 1
    assert record['networkFunctions'] == ['AMF', 'SMF']
    assert record['events'][0]['type'] == 'REGISTRATION_REQUESTED'
    assert all(e['core'] == 'oai' for e in engine.events)
    pdu = record['pduSessions'][0]
    assert (pdu['pduSessionId'], pdu['dnn'], pdu['ipv4'], pdu['state']) == (1, 'internet', '192.0.2.10', 'IP_ASSIGNED')
    assert 'SUPI: imsi-001010123456780' in pdu['events'][0]['rawEvidence']
    assert 'PAA IPv4: 192.0.2.10' in pdu['events'][0]['rawEvidence']
    count = len(engine.events)
    for raw in FIXTURE.read_text().splitlines():
        engine.feed(raw)
    engine.finish()
    assert len(engine.events) == count


@pytest.mark.parametrize('message', [
    'Received Initial UE Message, handling',
    'Received Service Request message (InitialUeMessage), handling...',
    'Received InitialUeMessage De-registration Request message, handling...',
    'Received De-registration Request message, handling...',
    'NF registered', 'Encoding RegistrationAccept message',
])
def test_oai_does_not_create_registration_from_unrelated_message(message):
    engine = Inspector()
    engine.feed(log(message))
    engine.expire(clock=999)
    assert not engine.attempts


@pytest.mark.parametrize('message', [
    'Received Registration Complete message, handling...',
    'Received Registration Complete message, processing',
    'Error when decoding Registration Complete',
    'Encoding RegistrationAccept message',
    '5GMM state transition: valid,  from state=COMM-PROC-INIT, event=REGISTRATION_COMPLETE_RECEIVED, to state=5GMM-REGISTERED',
    '5GMM state transition: not valid, state=COMM-PROC-INIT, event=REGISTRATION_COMPLETE_RECEIVED, reason=ignored',
    '5GMM state transition: COMM-PROC-INIT -> 5GMM-REGISTERED (event: [T3550_FINAL_EXPIRY])',
    '5GMM state transition: COMM-PROC-INIT -> 5GMM-REGISTERED (event: [LOWER_LAYER_FAILURE])',
    'Received Authentication Failure message, handling...',
    'ngKSI already in use, select a new ngKSI and restart the Authentication procedure!',
])
def test_incoming_completion_accept_timer_and_recoverable_auth_are_not_outcomes(message):
    engine = active()
    engine.feed(log(message, 2))
    assert engine.snapshot()['state'] == 'REGISTRATION_IN_PROGRESS'
    assert engine.snapshot()['failureEvidence'] is None
    engine.feed(log(COMPLETE, 3))
    assert engine.snapshot()['state'] == 'REGISTERED'


@pytest.mark.parametrize('message,stage', [
    ('MAC failure, reject the registration request', 'AUTHENTICATION'),
    ('Create Authentication Reject and send to UE', 'AUTHENTICATION'),
    ('Create Registration Reject and send to UE', 'REGISTRATION_COMPLETION'),
    ('5GMM state transition: COMM-PROC-INIT -> 5GMM-DEREGISTERED (event: [SECURITY_MODE_REJECT_RECEIVED])', 'NAS_SECURITY'),
    ('5GMM state transition: COMM-PROC-INIT -> 5GMM-DEREGISTERED (event: [REGISTRATION_REJECT_SENT])', 'REGISTRATION_COMPLETION'),
])
def test_explicit_oai_failures_keep_raw_evidence_without_inventing_cause(message, stage):
    engine = active()
    raw = log(message, 5)
    engine.feed(raw)
    record = engine.snapshot()
    assert record['state'] == 'FAILED'
    assert record['failureStage'] == stage
    assert record['protocolCause'] is None
    assert record['failureEvidence']['rawLogLine'] == raw
    assert record['failureEvidence']['component'] == 'amf_n1'
    engine.feed(log(message, 6))
    assert engine.snapshot() == record


def test_multiple_active_attempts_do_not_guess_identity_or_completion():
    engine = active()
    engine.feed(log(REQUEST, 2))
    engine.feed(log('Received IMSI 001010123456781', 3))
    engine.feed(log(COMPLETE, 4))
    engine.feed(log('Create Registration Reject and send to UE', 5))
    assert all(engine.is_active(r) for r in engine.attempts)
    assert engine.attempts[0]['imsi'] == 'imsi-001010123456780'
    assert engine.attempts[1]['imsi'] == 'imsi-001010123456781'
    assert len(engine.uncorrelated) == 2


def test_conflicting_identity_is_not_attached():
    engine = active()
    engine.feed(log('Received IMSI 001010123456781', 2))
    assert engine.snapshot()['imsi'] == 'imsi-001010123456780'
    assert engine.uncorrelated[-1]['rawEvidence'] == log('Received IMSI 001010123456781', 2)


def test_retry_same_ue_is_a_separate_attempt_and_timeouts_use_oai_year():
    engine = active()
    engine.feed(log('Create Registration Reject and send to UE', 2))
    engine.feed(log(REQUEST, 3), clock=1)
    engine.feed(log('Received IMSI 001010123456780', 4))
    assert len(engine.attempts) == 2
    assert len(engine.ues()) == 1
    assert engine.ues()[0]['sessionIds'] == ['registration-1', 'registration-2']
    engine.feed('[2026-10-04 12:00:31.000] [amf_app] [info] Statistics')
    assert engine.snapshot()['failureEvidence'] is None
    assert engine.snapshot()['failureStage'] == 'AFTER_REGISTRATION_REQUEST'
    assert engine.snapshot()['failedAt'].startswith('2026-10-04')


def test_deregistration_and_late_failure_do_not_change_success_result():
    engine = active()
    engine.feed(log(COMPLETE, 2))
    engine.feed(log('Create Registration Reject and send to UE', 3))
    assert engine.snapshot()['state'] == 'REGISTERED'
    engine.feed(log('5GMM state transition: 5GMM-REGISTERED -> 5GMM-DEREGISTERED (event: [UE_DEREGISTRATION_REQUEST_RECEIVED])', 4))
    assert engine.snapshot()['state'] == 'DEREGISTERED'
    assert engine.snapshot()['registrationStatus'] == 'SUCCESS'


def test_ansi_and_docker_timestamps_preserve_raw():
    engine = Inspector()
    raw = '\x1b[32moai-amf | 2026-10-04T11:00:00.000000001Z ' + log(REQUEST) + '\x1b[0m'
    engine.feed(raw)
    assert engine.events[0]['rawEvidence'] == raw
    assert engine.events[0]['timestamp'] == '2026-10-04T12:00:00.000'


def test_standalone_pdu_addresses_and_release_do_not_infer_sessions():
    engine = active()
    engine.feed(log('Allocated UE IPv4 Addr: 192.0.2.20', 3, 'smf_app'))
    engine.feed(log('Handle a PDU Session Release SM Context Request from an AMF', 4, 'smf_app'))
    assert not engine.snapshot()['pduSessions']
    assert len(engine.uncorrelated) == 2


def test_framing_prevents_foreign_container_address_binding():
    engine = active()
    for raw in (
        'oai-smf | ' + log('SMF context:', 3, 'smf_app'),
        'oai-smf | SUPI: imsi-001010123456780',
        'oai-smf | PDU Session ID: 1',
        'other-smf | PAA IPv4: 192.0.2.50',
        'oai-smf | PAA IPv4: 192.0.2.51',
    ):
        engine.feed(raw)
    engine.finish()
    assert engine.snapshot()['pduSessions'][0]['state'] == 'CONTEXT_OBSERVED'
    assert engine.snapshot()['pduSessions'][0]['ipv4'] is None


def test_pdu_dump_without_session_id_does_not_infer_release():
    engine = replay()
    engine.feed(log('SMF context:', 300, 'smf_app'))
    engine.feed('SUPI: imsi-001010123456780')
    engine.feed('PAA IPv4: 192.0.2.10')
    engine.finish()
    assert engine.snapshot()['pduSessions'][0]['state'] == 'IP_ASSIGNED'
    assert engine.uncorrelated


def test_oai_api_replay_finishes_last_block_and_reports_detection():
    with TestClient(create_app(mode='replay', replay=FIXTURE)) as client:
        import time
        for _ in range(100):
            health = client.get('/api/health').json()
            if health['linesProcessed'] == len(FIXTURE.read_text().splitlines()) and not health['logSource']['connected']:
                break
            time.sleep(.01)
        assert health['coreDetection']['core'] == 'oai'
        assert health['coreDetection']['adapterTarget'] == 'v2.2.2'
        record = client.get('/api/registration').json()
        assert record['state'] == 'REGISTERED'
        assert record['pduSessions'][0]['ipv4'] == '192.0.2.10'
        assert record['events'][0]['rawEvidence'].startswith('oai-amf |')


def test_mixed_health_is_analysis_error_even_if_reader_connected():
    app = create_app()
    app.state.inspector.feed(log(REQUEST))
    app.state.inspector.feed('[amf] INFO: InitialUEMessage')
    client = TestClient(app)
    assert client.get('/api/health').json()['status'] == 'error'
    assert client.get('/api/health').json()['coreDetection']['status'] == 'mixed'


def test_repeated_successful_registration_stays_with_same_ue():
    engine = active()
    engine.feed(log(COMPLETE, 2))
    engine.feed(log(REQUEST, 3))
    engine.feed(log('Received IMSI 001010123456780', 4))
    engine.feed(log(COMPLETE, 5))
    assert len(engine.ues()) == 1
    assert len(engine.attempts) == 2
    assert all(r['registrationStatus'] == 'SUCCESS' for r in engine.attempts)


def test_identity_free_completion_cannot_pick_sole_active_among_known_ues():
    engine = active()
    engine.feed(log(COMPLETE, 2))
    engine.feed(log(REQUEST, 3))
    engine.feed(log('Received IMSI 001010123456781', 4))
    engine.feed(log(COMPLETE, 5))
    assert engine.snapshot()['state'] == 'REGISTRATION_IN_PROGRESS'
    assert engine.uncorrelated[-1]['rawEvidence'] == log(COMPLETE, 5)


def dump(engine, fields):
    engine.feed(log('SMF context:', 100, 'smf_app'))
    engine.feed('SUPI: imsi-001010123456780')
    for field in fields:
        engine.feed(field)
    engine.finish()


def test_explicit_multiple_pdu_sessions_keep_their_own_addresses():
    engine = active()
    dump(engine, ['PDU Session ID: 1', 'DNN: internet', 'PAA IPv4: 192.0.2.1',
                  'UPF graph: synthetic display text',
                  'PDU Session ID: 2', 'DNN: ims', 'PAA IPv4: 192.0.2.2'])
    sessions = engine.snapshot()['pduSessions']
    assert [(s['pduSessionId'], s['dnn'], s['ipv4']) for s in sessions] == [
        (1, 'internet', '192.0.2.1'), (2, 'ims', '192.0.2.2')]


def test_pdu_after_reregistration_stays_uncorrelated():
    engine = active()
    engine.feed(log(COMPLETE, 2))
    engine.feed(log(REQUEST, 3))
    engine.feed(log('Received IMSI 001010123456780', 4))
    dump(engine, ['PDU Session ID: 1', 'PAA IPv4: 192.0.2.1'])
    assert all(not r['pduSessions'] for r in engine.attempts)
    assert 'multiple registration' in engine.uncorrelated[-1]['reason']


@pytest.mark.parametrize('address', ['0.0.0.0', '999.1.1.1', '::', ''])
def test_invalid_or_unspecified_addresses_do_not_show_assigned_ip(address):
    engine = active()
    dump(engine, ['PDU Session ID: 1', 'PAA IPv4: ' + address])
    assert engine.snapshot()['pduSessions'][0]['state'] == 'CONTEXT_OBSERVED'
    assert engine.snapshot()['pduSessions'][0]['ipv4'] is None


def test_repeated_session_id_in_same_dump_is_ambiguous():
    engine = active()
    dump(engine, ['PDU Session ID: 1', 'PAA IPv4: 192.0.2.1',
                  'PDU Session ID: 1', 'PAA IPv4: 192.0.2.2'])
    assert not engine.snapshot()['pduSessions']
    assert 'ambiguous' in engine.uncorrelated[-1]['reason']


def test_oversized_smf_dump_is_retained_as_unresolved_not_attached():
    engine = active()
    dump(engine, ['PDU Session ID: 1'] + ['graph output'] * 130)
    assert not engine.snapshot()['pduSessions']
    assert 'block limit' in engine.uncorrelated[-1]['reason']


def test_empty_dnn_does_not_consume_next_field_and_ipv6_is_preserved():
    engine = active()
    dump(engine, ['PDU Session ID: 1', 'DNN:', 'PAA IPv4: 192.0.2.1', 'PAA IPv6: 2001:db8::1'])
    pdu = engine.snapshot()['pduSessions'][0]
    assert pdu['dnn'] is None
    assert pdu['ipv4'] == '192.0.2.1'
    assert pdu['ipv6'] == '2001:db8::1'


def test_received_security_reject_is_observed_even_if_state_machine_rejects_event():
    # Synthetic reconstruction of the v2.2.2 live lab's null-integrity rejection.
    engine = active()
    raw = log('Received Security Mode Reject message, handling...', 2)
    engine.feed(raw)
    engine.feed(log('5GMM state transition: not valid, state=COMM-PROC-INIT, '
                    'event=SECURITY_MODE_REJECT_RECEIVED, reason=No transition: '
                    'state=4 event=SECURITY_MODE_REJECT_RECEIVED', 3))
    record = engine.snapshot()
    assert record['state'] == 'FAILED'
    assert record['failureStage'] == 'NAS_SECURITY'
    assert record['failureReason'] == 'UE sent Security Mode Reject'
    assert record['protocolCause'] is None
    assert record['failureEvidence']['rawLogLine'] == raw
    assert record['failureEvidence']['matchedRule'] == 'oai_security_mode_reject_received'
