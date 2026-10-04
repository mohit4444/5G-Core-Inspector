"""Synthetic multi-UE and PDU test data, not a captured multi-UE trace."""
from fastapi.testclient import TestClient
from app import create_app
from engine import Inspector

A = 'imsi-001010123456780'
B = 'imsi-001010123456781'


def line(message, ms=0, module='gmm'):
    return f'09/06 16:00:{ms // 1000:02d}.{ms % 1000:03d} [{module}] INFO: {message}'


def register(i, imsi=A, offset=0, ngap=1):
    i.feed(line(f'InitialUEMessage AMF_UE_NGAP_ID[{ngap}]', offset, 'amf'), clock=offset / 1000)
    i.feed(line(f'[{imsi}] Registration request AMF_UE_NGAP_ID[{ngap}]', offset+1))
    i.feed(line(f'[{imsi}] Registration complete', offset+538))
    return i.attempts[-1]


def address(i, imsi=A, ip='10.45.1.2', dnn='internet', ms=1000):
    raw = line(f'UE SUPI[{imsi}] DNN[{dnn}] IPv4[{ip}] IPv6[]', ms, 'smf')
    i.feed(raw)
    return raw


def test_interleaved_ues_and_identity_links():
    i = Inspector(2026)
    i.feed(line('InitialUEMessage AMF_UE_NGAP_ID[1] RAN_UE_NGAP_ID[0]',0,'amf'))
    i.feed(line('InitialUEMessage AMF_UE_NGAP_ID[2] RAN_UE_NGAP_ID[1]',1,'amf'))
    i.feed(line('[suci-test-a] SUCI AMF_UE_NGAP_ID[1]',2))
    i.feed(line('[suci-test-b] SUCI AMF_UE_NGAP_ID[2]',3))
    i.feed(line('[suci-test-b] Registration request',4))
    i.feed(line('[suci-test-a] Registration request',5))
    i.feed(line(f'[{B}] Registration complete AMF_UE_NGAP_ID[2]',500))
    i.feed(line(f'[{A}] Registration complete AMF_UE_NGAP_ID[1]',538))
    assert len(i.ues()) == 2
    a,b = i.attempts
    assert (a['imsi'],a['suci'],a['durationMs']) == (A,'suci-test-a',538)
    assert (b['imsi'],b['suci'],b['durationMs']) == (B,'suci-test-b',499)
    assert a['state'] == b['state'] == 'REGISTERED'
    address(i,B,'10.45.1.3',ms=600)
    address(i,A,ms=601)
    i.feed(line(f'[{A}] Deregistration request',1000))
    assert a['state'] == 'DEREGISTERED' and b['state'] == 'REGISTERED'
    assert a['pduSessions'][0]['ipv4'] == '10.45.1.2'
    assert b['pduSessions'][0]['ipv4'] == '10.45.1.3'


def test_ambiguous_lines_are_visible_and_do_not_guess():
    i = Inspector(2026)
    i.feed(line('InitialUEMessage',0,'amf'))
    i.feed(line('InitialUEMessage',1,'amf'))
    for raw in (line('Registration request',2),line(f'[{A}] Registration complete',538),
                line('RAN_UE_NGAP_ID[0] AMF_UE_NGAP_ID[1]',3,'amf')):
        i.feed(raw)
    assert len(i.uncorrelated) == 3
    assert all(r['state'] == 'UE_DETECTED' and r['imsi'] is None for r in i.attempts)
    assert 'Registration complete' in i.uncorrelated[1]['rawEvidence']


def test_conflicting_identifiers_do_not_cross_ues():
    i = Inspector(2026)
    i.feed(line(f'InitialUEMessage [{A}] AMF_UE_NGAP_ID[1]',0,'amf'))
    i.feed(line(f'InitialUEMessage [{B}] AMF_UE_NGAP_ID[2]',1,'amf'))
    i.feed(line(f'[{A}] Registration complete AMF_UE_NGAP_ID[2]',538))
    assert all(r['state'] == 'UE_DETECTED' for r in i.attempts)
    assert len(i.uncorrelated) == 1


def test_independent_timeouts_and_reject():
    i = Inspector(2026,timeout=2)
    i.feed(line(f'InitialUEMessage [{A}]',0,'amf'),clock=0)
    i.feed(line(f'InitialUEMessage [{B}]',1000,'amf'),clock=1)
    i.expire(clock=2)
    assert i.attempts[0]['state'] == 'FAILED'
    assert i.attempts[1]['state'] == 'UE_DETECTED'
    i.feed(line(f'[{B}] Registration reject',2100))
    assert i.attempts[1]['state'] == 'FAILED'
    assert i.events[-1]['sessionId'] == 'registration-2'


def test_pdu_real_message_shapes_and_preserved_registration():
    i = Inspector(2026); r = register(i)
    i.feed(line(f'UE SUPI[{A}] DNN[internet] S_NSSAI[SST:1 SD:0xffffff] smContextRef[NULL] smContextResourceURI[NULL]',600))
    raw = address(i,ms=601)
    s = r['pduSessions'][0]
    assert s['state'] == 'IP_ASSIGNED' and s['pduSessionId'] is None
    assert s['sst'] == 1 and s['sd'] == '0xffffff'
    assert s['events'][-1]['rawEvidence'] == raw
    i.feed(line(f'[{A}:1:11][0:0:NULL] /nsmf-pdusession/v1/sm-contexts/{{smContextRef}}/modify',700,'amf'))
    assert s['pduSessionId'] == 1 and s['state'] == 'IP_ASSIGNED'
    i.feed(line(f'[{A}] Deregistration request',1000))
    assert s['state'] == 'IP_ASSIGNED'  # No inferred PDU release from deregistration.
    i.feed(line(f'Removed Session: UE IMSI:[{A}] DNN:[internet:1] IPv4:[10.45.1.2] IPv6:[]',1001,'smf'))
    i.feed(line(f'[{A}:1] Release SM Context [state:1]',1002,'amf'))
    assert len(r['pduSessions']) == 1 and s['state'] == 'RELEASED'
    assert s['releasedAt'] == '2026-09-06T16:00:01.001'
    assert r['durationMs'] == 538 and r['registrationStatus'] == 'SUCCESS'
    assert r['networkFunctions'] == ['AMF', 'SMF']


def test_pdu_noise_unknown_identity_and_empty_addresses():
    i = Inspector(2026); r = register(i)
    for msg in ('[Added] Number of SMF-Sessions is now 1','PFCP associated','NF Service [nsmf-pdusession]'):
        i.feed(line(msg,600,'smf'))
    assert r['pduSessions'] == []
    address(i,B,ms=601)
    assert r['pduSessions'] == [] and len(i.uncorrelated) == 1
    address(i,ip='',ms=602)
    assert r['pduSessions'][0]['state'] == 'CONTEXT_OBSERVED'
    assert r['pduSessions'][0]['ipv4'] is None


def test_multiple_pdu_sessions_and_ambiguous_psi():
    i = Inspector(2026); r = register(i)
    address(i,dnn='internet',ms=600)
    address(i,dnn='ims',ip='10.46.1.2',ms=601)
    i.feed(line(f'[{A}:1:11][0:0:NULL] /nsmf-pdusession/v1/sm-contexts/{{smContextRef}}/modify',700,'amf'))
    assert all(s['pduSessionId'] is None for s in r['pduSessions'])
    assert len(i.uncorrelated) == 1
    i.feed(line(f'Removed Session: UE IMSI:[{A}] DNN:[ims:2] IPv4:[10.46.1.2] IPv6:[]',1000,'smf'))
    assert r['pduSessions'][1]['state'] == 'RELEASED'
    assert r['pduSessions'][0]['state'] == 'IP_ASSIGNED'


def test_pdu_duplicate_and_new_generation():
    i = Inspector(2026); r = register(i)
    raw = address(i,ms=600); count = len(i.events)
    i.feed(raw); assert len(i.events) == count
    i.feed(line(f'Removed Session: UE IMSI:[{A}] DNN:[internet:1] IPv4:[10.45.1.2] IPv6:[]',1000,'smf'))
    address(i,ms=1100)
    assert len(r['pduSessions']) == 2
    assert r['pduSessions'][0]['state'] == 'RELEASED'
    assert r['pduSessions'][1]['state'] == 'IP_ASSIGNED'


def test_reregistration_and_reused_ngap_history():
    i = Inspector(2026)
    first = register(i)
    address(i,ms=600)
    i.feed(line(f'[{A}] Deregistration request',1000))
    second = register(i,offset=2000)
    address(i,ip='10.45.1.4',ms=2600)
    assert len(i.ues()) == 1 and len(i.ues()[0]['sessionIds']) == 2
    assert first['pduSessions'][0]['ipv4'] == '10.45.1.2'
    assert second['pduSessions'][0]['ipv4'] == '10.45.1.4'


def test_multi_api():
    app = create_app()
    i = app.state.inspector
    register(i); register(i,B,offset=1000,ngap=2)
    address(i,ms=1600)
    client = TestClient(app)
    assert len(client.get('/api/ues').json()) == 2
    assert len(client.get('/api/registrations').json()) == 2
    assert client.get('/api/registration?sessionId=registration-1').json()['pduSessions'][0]['ipv4'] == '10.45.1.2'
    assert client.get('/api/registration?sessionId=missing').status_code == 404
    assert all(e['sessionId']=='registration-1' for e in client.get('/api/events?sessionId=registration-1').json())
    assert client.get('/api/health').json()['ueCount'] == 2
    assert client.get('/api/uncorrelated').json() == []
    assert '<div id="root"></div>' in client.get('/').text


def test_delayed_removal_updates_original_attempt():
    i = Inspector(2026)
    first = register(i); address(i,ms=600)
    second = register(i,offset=1000)
    address(i,ip='10.45.1.4',ms=1600)
    i.feed(line(f'Removed Session: UE IMSI:[{A}] DNN:[internet:1] IPv4:[10.45.1.2] IPv6:[]',2000,'smf'))
    assert first['pduSessions'][0]['state'] == 'RELEASED'
    assert second['pduSessions'][0]['state'] == 'IP_ASSIGNED'


def test_ambiguous_removal_does_not_change_either_attempt():
    i = Inspector(2026)
    first = register(i); address(i,ms=600)
    second = register(i,offset=1000); address(i,ms=1600)
    i.feed(line(f'Removed Session: UE IMSI:[{A}] DNN:[internet:1] IPv4:[10.45.1.2] IPv6:[]',2000,'smf'))
    assert first['pduSessions'][0]['state'] == second['pduSessions'][0]['state'] == 'IP_ASSIGNED'
    assert len(i.uncorrelated) == 1


def test_known_suci_alias_groups_attempts_without_inventing_imsi():
    i = Inspector(2026)
    i.feed(line('InitialUEMessage [suci-test-a]',0,'amf'))
    i.feed(line('Registration complete',500))
    i.feed(line('InitialUEMessage [suci-test-a]',1000,'amf'))
    i.feed(line(f'[{A}] Registration complete',1500))
    assert len(i.ues()) == 1
    assert i.attempts[0]['imsi'] is None
    assert i.ues()[0]['identity'] == A
