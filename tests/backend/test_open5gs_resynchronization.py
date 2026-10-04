"""Synthetic regressions for recoverable Open5GS authentication sync failures."""
import pytest

from backend.core.engine import Inspector


def active():
    engine = Inspector(2026)
    engine.feed('09/06 12:00:00.000 [amf] INFO: InitialUEMessage', clock=0)
    engine.feed('09/06 12:00:00.010 [gmm] INFO: [imsi-001010123456780] Registration request')
    return engine


@pytest.mark.parametrize('message', [
    'Authentication failure [21]',
    'Authentication failure(Synch failure[count=0])',
])
def test_sync_failure_preserves_evidence_and_allows_observed_completion(message):
    engine = active()
    raw = f'09/06 12:00:00.020 [gmm] WARNING: [imsi-001010123456780] {message}'
    engine.feed(raw)
    record = engine.snapshot()
    assert record['state'] == 'REGISTRATION_IN_PROGRESS'
    assert record['lastSuccessfulStage'] == 'REGISTRATION_REQUEST_RECEIVED'
    assert record['failureReason'] is None
    assert record['events'][-1]['type'] == 'AUTHENTICATION_SYNC_FAILURE'
    assert record['events'][-1]['rawEvidence'] == raw
    engine.feed('09/06 12:00:00.110 [gmm] INFO: [imsi-001010123456780] Registration complete')
    assert engine.snapshot()['registrationStatus'] == 'SUCCESS'
    assert engine.snapshot()['durationMs'] == 110
    assert not any(e['type'] == 'REGISTRATION_FAILED' for e in engine.events)


def test_sync_failure_still_requires_completion_or_times_out():
    engine = active()
    engine.feed('09/06 12:00:00.020 [gmm] WARNING: Authentication failure [21]')
    engine.expire(clock=30)
    record = engine.snapshot()
    assert record['state'] == 'FAILED'
    assert record['diagnosisConfidence'] == 'STAGE_LEVEL'
    assert record['failureEvidence'] is None


def test_repeated_sync_failure_can_end_in_an_explicit_reject():
    engine = active()
    for ms, message in [(20, 'Authentication failure [21]'),
                        (21, 'Authentication failure(Synch failure[count=0])'),
                        (40, 'Authentication failure(Synch failure[count=1])')]:
        engine.feed(f'09/06 12:00:00.{ms:03d} [gmm] WARNING: {message}')
    raw = ('09/06 12:00:00.041 [gmm] WARNING: '
           'Too many authentication synch failures, sending AUTHENTICATION REJECT')
    engine.feed(raw)
    record = engine.snapshot()
    assert record['state'] == 'FAILED'
    assert record['failureStage'] == 'AUTHENTICATION'
    assert record['failureEvidence']['rawLogLine'] == raw
    assert sum(e['type'] == 'AUTHENTICATION_SYNC_FAILURE' for e in engine.events) == 3


@pytest.mark.parametrize('message', ['Authentication failure [20]', 'Authentication failure [210]',
                                  'Authentication failure(MAC failure)'])
def test_other_authentication_failures_remain_terminal(message):
    engine = active()
    engine.feed(f'09/06 12:00:00.020 [gmm] WARNING: {message}')
    assert engine.snapshot()['failureStage'] == 'AUTHENTICATION'
    assert engine.snapshot()['state'] == 'FAILED'


def test_identity_free_sync_failure_does_not_guess_between_ues():
    engine = active()
    engine.feed('09/06 12:00:00.015 [amf] INFO: InitialUEMessage', clock=.015)
    engine.feed('09/06 12:00:00.016 [gmm] INFO: [imsi-001010123456781] Registration request')
    raw = '09/06 12:00:00.020 [gmm] WARNING: Authentication failure [21]'
    engine.feed(raw)
    assert len(engine.attempts) == 2
    assert all(r['state'] == 'REGISTRATION_IN_PROGRESS' for r in engine.attempts)
    assert engine.uncorrelated[-1]['rawEvidence'] == raw


def test_sync_failure_with_conflicting_identity_is_unassigned():
    engine = active()
    raw = '09/06 12:00:00.020 [gmm] WARNING: [imsi-001010123456781] Authentication failure [21]'
    engine.feed(raw)
    assert engine.uncorrelated[-1]['rawEvidence'] == raw
    assert not any(e['type'] == 'AUTHENTICATION_SYNC_FAILURE' for e in engine.events)


def test_sync_failure_without_active_attempt_does_not_create_one():
    engine = Inspector(2026)
    raw = '09/06 12:00:00.020 [gmm] WARNING: Authentication failure [21]'
    engine.feed(raw)
    assert not engine.attempts
    assert engine.uncorrelated[-1]['rawEvidence'] == raw
