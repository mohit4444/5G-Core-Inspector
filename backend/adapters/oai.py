"""OAI CN5G v2.2.2 text logs. See README.md for supported coverage.

Upstream reference commits in openairinterface/oai-cn5g-amf and oai-cn5g-smf:
AMF b2f19d1a4a6f23471f218316b33adc61505035f7;
SMF 9d9cacd037d32b9f99a9d2610c1efd18a4a445ef.

Receiving/encoding a message is not proof of accepted registration. Only an
applied REGISTRATION_COMPLETE_RECEIVED transition confirms completion here.
Identity-free messages require a single known UE and a single active attempt.
"""
import ipaddress
import re
from datetime import datetime
from ..core.pdu import observe_pdu

KEY = 'oai'
LABEL = 'OAI 5G Core'
TARGET = 'v2.2.2'
HEADER = re.compile(
    r'\[(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3,6})\]\s+'
    r'\[(?P<component>[a-z0-9_]+)\]\s+'
    r'\[(?P<severity>trace|debug|info|start|startup|warn|warning|error|critical|off)\]\s*(?P<message>.*)$', re.I)
CORE_COMPONENT = re.compile(r'^(?:amf|smf|ausf|udm|udr|nrf|upf)_(?:app|n1|n2|n4|sbi|api_server)$')
TRANSITION = re.compile(r'^5GMM state transition: (\S+) -> (\S+) \(event: \[([A-Z0-9_]+)\]\)$')
REQUEST = re.compile(r'^Received Registration Request(?: message)?, handling\.\.\.$')
# Deliberately exclude generic Authentication Failure: OAI can resynchronize and retry.
FAILURES = {
    'Received Security Mode Reject message, handling...':
        ('oai_security_mode_reject_received', 'NAS_SECURITY', 'UE sent Security Mode Reject'),
    'MAC failure, reject the registration request':
        ('oai_mac_failure', 'AUTHENTICATION', 'MAC failure during authentication'),
    'Create Authentication Reject and send to UE':
        ('oai_authentication_reject', 'AUTHENTICATION', 'Core initiated Authentication Reject'),
    'Create Registration Reject and send to UE':
        ('oai_registration_reject', 'REGISTRATION_COMPLETION', 'Core initiated Registration Reject'),
}
FAILURE_EVENTS = {
    'REGISTRATION_REJECT_SENT': ('oai_registration_reject', 'REGISTRATION_COMPLETION', 'Registration rejected'),
    'AUTHENTICATION_REJECT_SENT': ('oai_authentication_reject', 'AUTHENTICATION', 'Authentication rejected'),
    'SECURITY_MODE_REJECT_RECEIVED': ('oai_security_mode_reject', 'NAS_SECURITY', 'Security Mode Reject received'),
}


def detect(line):
    match = HEADER.search(line)
    return bool(match and CORE_COMPONENT.fullmatch(match['component'].lower()))


def identifiers(message):
    """Only labeled, unambiguous identifiers; never derive IMSI from concealed SUCI."""
    result = {}
    for key, pattern in (
        ('imsi', r'\b(?:Received IMSI|SUPI|IMSI)\s*[:(]?\s*(?:imsi-)?(\d{5,15})\b'),
        ('suci', r'\b(suci-[\w-]+)\b'),
        ('amfUeNgapId', r'\bamf_ue_ngap_id\s*[:(]?\s*(\d+)\b'),
        ('ranUeNgapId', r'\bran_ue_ngap_id\s*[:(]?\s*(\d+)\b'),
    ):
        values = set(re.findall(pattern, message, re.I))
        if len(values) > 1:
            return None
        if values:
            value = values.pop()
            result[key] = ('imsi-' + value if key == 'imsi' else
                           int(value) if key.endswith('NgapId') else value)
    search = re.fullmatch(r'Key for UE context search: (\d+)', message)
    if search:
        result['amfUeNgapId'] = int(search[1])
    return result


def correlate(engine, ids, candidates):
    # An unlabeled event may belong to an already registered UE. Do not select
    # the sole active UE when other identities also exist in this stream.
    if not ids and len(engine.latest_identities()) != 1:
        return None
    # Explicit identifiers can enrich the uniquely compatible active attempt,
    # following the shared correlation contract (conflicting IDs exclude it).
    return engine.correlate(ids, candidates, allow_enrichment=True)


def producer(prefix):
    # Docker timestamps are per-line; the Compose service prefix is stable.
    return re.sub(r'\d{4}-\d\d-\d\dT\S+\s*$', '', prefix).strip()


def flush(engine):
    block = engine.adapter_state.pop('smf_block', None)
    if not block:
        return
    raw = '\n'.join(block['raw'])
    if raw in engine.seen:
        return
    engine.seen.add(raw)
    body = '\n'.join(block['body'])
    supis = re.findall(r'^[ \t]*SUPI:[ \t]*(imsi-\d{5,15})[ \t]*$', body, re.M)
    sections = re.split(r'^[ \t]*PDU Session ID:[ \t]*(\d{1,2})[ \t]*$', body, flags=re.M)
    if len(supis) != 1 or len(sections) < 3:
        engine.unresolved(block['stamp'], raw, 'OAI SMF context lacks explicit SUPI and PDU session ID')
        return
    if len(set(sections[1::2])) != len(sections[1::2]):
        engine.unresolved(block['stamp'], raw, 'OAI SMF dump repeats a PDU session ID; ambiguous context')
        return
    if len([r for r in engine.attempts if r['imsi'] == supis[0]]) > 1:
        engine.unresolved(block['stamp'], raw, 'OAI PDU context matches multiple registration attempts')
        return
    for index in range(1, len(sections), 2):
        psi, details = int(sections[index]), sections[index + 1]
        if not 1 <= psi <= 15:
            engine.unresolved(block['stamp'], raw, 'Invalid OAI PDU session ID')
            continue
        attrs = {'pduSessionId': psi}
        for key, label in (('dnn', 'DNN'), ('ipv4', 'PAA IPv4'), ('ipv6', 'PAA IPv6')):
            values = re.findall(r'^[ \t]*' + label + r':[ \t]*([^\n]*)$', details, re.M)
            if len(values) == 1:
                value = values[0].strip()
                if not value:
                    continue
                if key.startswith('ipv'):
                    try:
                        address = ipaddress.ip_address(value)
                        if address.is_unspecified or address.version != int(key[-1]):
                            continue
                    except ValueError:
                        continue
                attrs[key] = value
        observe_pdu(engine, 'smf', {'imsi': supis[0]}, block['stamp'], raw, 'log', attrs,
                    address=bool(attrs.get('ipv4') or attrs.get('ipv6')))


def feed(engine, raw, line, clock=None):
    header = HEADER.search(line)
    if not header:
        block = engine.adapter_state.get('smf_block')
        if block:
            content = line
            prefix = block['producer']
            if prefix:
                if not content.startswith(prefix):
                    flush(engine)
                    return
                content = content[len(prefix):].lstrip()
            content = re.sub(r'^\d{4}-\d\d-\d\dT\S+\s+', '', content)
            # One logger call can include graph/policy text between sessions.
            # Preserve it, but extract only the explicitly labeled context fields.
            # A timestamped header or foreign producer ends the block above.
            if len(block['raw']) >= 128 or sum(map(len, block['raw'])) + len(raw) > 65536:
                engine.adapter_state.pop('smf_block')
                engine.unresolved(block['stamp'], '\n'.join(block['raw']),
                                  'OAI SMF context exceeded the evidence block limit')
            else:
                block['raw'].append(raw)
                block['body'].append(content)
        return
    flush(engine)
    if raw in engine.seen:
        return
    engine.seen.add(raw)
    try:
        stamp = datetime.fromisoformat(header['stamp'])
    except ValueError:
        return
    engine.expire(stamp=stamp)
    component = header['component'].lower()
    message = header['message'].strip()
    severity = header['severity'].upper()
    if component == 'smf_app':
        if message == 'SMF context:':
            engine.adapter_state['smf_block'] = {
                'raw': [raw], 'body': [], 'stamp': stamp,
                'producer': producer(line[:header.start()])}
        elif ('Allocated UE IPv' in message or 'UE IPv4 Address' in message or
              'PDU Session' in message or 'PDU session' in message):
            # Standalone OAI allocation/request/release logs lack a complete
            # SUPI + PSI association. Retain evidence without inventing one.
            engine.unresolved(stamp, raw, 'OAI PDU message lacks a framed SUPI/session association')
        return
    if component not in ('amf_n1', 'amf_app', 'amf_n2'):
        return
    ids = identifiers(message)
    if ids is None:
        engine.unresolved(stamp, raw, 'OAI message contains conflicting identifiers')
        return
    if component == 'amf_n1' and REQUEST.fullmatch(message):
        record = engine.start_attempt(stamp, raw, 'log', ids, clock,
                                      kind='REGISTRATION_REQUEST_RECEIVED')
        engine.observe_network_function(record, 'amf')
        return
    transition = TRANSITION.fullmatch(message) if component == 'amf_n1' else None
    event = transition[3] if transition else None
    completed = (event == 'REGISTRATION_COMPLETE_RECEIVED' and
                 transition[2] == '5GMM-REGISTERED')
    deregistered = (event == 'UE_DEREGISTRATION_REQUEST_RECEIVED' and
                   transition[2] == '5GMM-DEREGISTERED')
    failure = (FAILURE_EVENTS.get(event) or FAILURES.get(message)) if component == 'amf_n1' else None
    # Restrict enrichment to concrete lookup/identity evidence. Error strings,
    # old/new context comparisons, notifications and statistics are not bindings.
    enrichment = (component == 'amf_app' and message.startswith('Key for UE context search: ')) or (
        component == 'amf_n1' and re.match(r'^(?:Received IMSI |SUPI |Associating SUPI \()', message))
    if not (completed or deregistered or failure or (enrichment and ids)):
        return
    candidates = engine.latest_identities() if deregistered else [r for r in engine.attempts if engine.is_active(r)]
    record = correlate(engine, ids, candidates)
    if record is None:
        engine.unresolved(stamp, raw, 'OAI registration evidence has no unique compatible UE/attempt')
        return
    record.update(ids)
    engine.observe_network_function(record, 'amf')
    if enrichment:
        engine.event('UE_IDENTITY_RESOLVED' if any(k in ids for k in ('imsi', 'suci'))
                     else 'UE_CONTEXT_IDENTIFIED', stamp, raw, 'log', record)
    elif completed:
        record.update(state='REGISTERED', registrationStatus='SUCCESS',
                      lastSuccessfulStage='REGISTRATION_COMPLETE_RECEIVED',
                      completedAt=stamp.isoformat(timespec='milliseconds'),
                      durationMs=round((stamp - datetime.fromisoformat(record['startedAt'])).total_seconds() * 1000))
        engine.event('REGISTRATION_COMPLETED', stamp, raw, 'log', record)
    elif deregistered and record['state'] == 'REGISTERED':
        record.update(state='DEREGISTERED', deregistrationRequestedAt=stamp.isoformat(timespec='milliseconds'))
        engine.event('DEREGISTRATION_REQUESTED', stamp, raw, 'log', record)
    elif failure:
        name, stage, reason = failure
        engine.fail(stamp, stage, reason, 'EXACT', raw, 'log', record, name,
                    component, severity, identifiers=ids)
