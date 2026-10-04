"""Open5GS log adapter. Keep vendor patterns outside the shared engine."""
import re
from datetime import datetime
from .open5gs_failures import match_failure
from ..core.pdu import observe_pdu

IDS = {'ranUeNgapId': r'RAN_UE_NGAP_ID\[(\d+)\]',
       'amfUeNgapId': r'AMF_UE_NGAP_ID\[(\d+)\]', 'tac': r'TAC\[(\d+)\]',
       'cellId': r'CellID\[([^\]]+)\]', 'suci': r'\[(suci-[^\]\s]+)\]',
       'imsi': r'\[(imsi-\d+)(?=[:\]])'}

KEY = 'open5gs'
LABEL = 'Open5GS'
TARGET = None  # Deployed build; no version can be inferred from message format.
STAMP = re.compile(r'\b(\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\b')
SIGNATURE = re.compile(r'^[^\[\r\n]*\[(?:amf|gmm|smf|ausf|udm|nrf|upf|pfcp|sbi)\]\s+(?:TRACE|DEBUG|INFO|WARNING|WARN|ERROR|FATAL):', re.I)


def detect(line):
    return bool(SIGNATURE.search(line))


def feed(engine, raw, line, clock=None):
    match = STAMP.search(line)
    source = 'log' if match else 'receipt'
    try:
        stamp = (datetime.strptime(f'{engine.year}/{match[1]}', '%Y/%m/%d %H:%M:%S.%f')
                 if match else datetime.now())
    except ValueError:
        return
    # Log time advances replay deadlines even for noise, but noise cannot create a session.
    if match:
        engine.expire(stamp=stamp)
    module = re.search(r'\[(amf|gmm|smf|ausf|udm)\]', line, re.I)
    if not module:
        return
    identifiers = {}
    failure_rule = cause = None
    for key, pattern in IDS.items():
        found = re.search(pattern, line)
        if found:
            identifiers[key] = int(found[1]) if key in ('ranUeNgapId', 'amfUeNgapId', 'tac') else found[1]
    component = module[1].lower()
    severity_match = re.search(r'\]\s+(TRACE|DEBUG|INFO|WARNING|WARN|ERROR|FATAL):', line, re.I)
    severity = severity_match[1].upper() if severity_match else None
    if track_pdu(engine, component, line, identifiers, stamp, raw, source):
        return
    if component == 'smf':
        return
    if re.search(r'\bDeregistration\b', line, re.I):
        if re.search(r'\bDeregistration request\b', line, re.I):
            candidates = engine.latest_identities()
            record = engine.correlate(identifiers, candidates, allow_enrichment=True)
            if record is not None and record['state'] == 'REGISTERED':
                record.update(identifiers)
                record['state'] = 'DEREGISTERED'
                record['deregistrationRequestedAt'] = stamp.isoformat(timespec='milliseconds')
                engine.event('DEREGISTRATION_REQUESTED', stamp, raw, source, record)
            elif record is None:
                engine.unresolved(stamp, raw, 'Deregistration has no unique matching UE')
        return
    initial = bool(re.search(r'\bInitialUEMessage\b', line))
    if initial:
        record = engine.start_attempt(stamp, raw, source, identifiers, clock)
    else:
        requested = re.search(r'\bRegistration request\b', line, re.I)
        completed = re.search(r'\bRegistration complete\b', line, re.I)
        failure_rule, cause = match_failure(component, line)
        # Only actual context/identity messages may enrich a registration.
        enrichment = re.search(r'RAN_UE_NGAP_ID|AMF_UE_NGAP_ID|\bSUCI\b', line)
        if not (requested or completed or failure_rule or enrichment):
            return
        candidates = [r for r in engine.attempts if engine.is_active(r)]
        if not candidates and not (requested or completed or failure_rule):
            return
        record = engine.correlate(identifiers, candidates, allow_enrichment=True)
        if record is None:
            engine.unresolved(stamp, raw, 'Registration evidence has no unique compatible active attempt')
            return
        record.update(identifiers)
    engine.observe_network_function(record, component)
    if any(k in identifiers for k in ('ranUeNgapId', 'amfUeNgapId', 'tac', 'cellId')):
        engine.event('UE_CONTEXT_IDENTIFIED', stamp, raw, source, record)
    if any(k in identifiers for k in ('suci', 'imsi')):
        engine.event('UE_IDENTITY_RESOLVED', stamp, raw, source, record)
    if re.search(r'\bRegistration request\b', line, re.I):
        record['state'] = 'REGISTRATION_IN_PROGRESS'
        record['lastSuccessfulStage'] = 'REGISTRATION_REQUEST_RECEIVED'
        engine.event('REGISTRATION_REQUESTED', stamp, raw, source, record)
    elif re.search(r'\bRegistration complete\b', line, re.I):
        record.update(state='REGISTERED', registrationStatus='SUCCESS',
                      lastSuccessfulStage='REGISTRATION_COMPLETE_RECEIVED',
                      completedAt=stamp.isoformat(timespec='milliseconds'),
                      durationMs=round((stamp - datetime.fromisoformat(record['startedAt'])).total_seconds() * 1000))
        engine.event('REGISTRATION_COMPLETED', stamp, raw, source, record)
    elif failure_rule:
        engine.fail(stamp, failure_rule['failure_stage'], failure_rule['reason'],
                  failure_rule['confidence'], raw, source, record,
                  failure_rule['name'], component, severity, cause, identifiers)


def track_pdu(engine, module, line, identifiers, stamp, raw, source):
    removed = module == 'smf' and 'Removed Session: UE IMSI:' in line
    address = module == 'smf' and 'UE SUPI[' in line and 'IPv4[' in line
    context = module == 'gmm' and 'UE SUPI[' in line and 'smContextRef[' in line
    modify = module == 'amf' and '/nsmf-pdusession/v1/sm-contexts/{smContextRef}/modify' in line
    release = module == 'amf' and 'Release SM Context [state:' in line
    if not any((removed, address, context, modify, release)):
        return False
    dnn_match = re.search(r'DNN:?\[([^\]]+)\]', line)
    dnn = dnn_match[1] if dnn_match else None
    psi = None
    if removed and dnn:
        parts = dnn.rsplit(':', 1)
        if len(parts) == 2 and parts[1].isdigit():
            dnn, psi = parts[0], int(parts[1])
    compound = re.search(r'\[imsi-\d+:(\d+)(?=[:\]])', line)
    if compound:
        psi = int(compound[1])
    ipv4 = re.search(r'IPv4:?\[([^\]]*)\]', line)
    ipv6 = re.search(r'IPv6:?\[([^\]]*)\]', line)
    attrs = {'dnn': dnn, 'pduSessionId': psi,
             'ipv4': ipv4[1] or None if ipv4 else None,
             'ipv6': ipv6[1] or None if ipv6 else None}
    slice_match = re.search(r'S_NSSAI\[SST:(\d+) SD:([^\]]+)\]', line)
    if slice_match:
        attrs.update(sst=int(slice_match[1]), sd=slice_match[2])
    return observe_pdu(engine, module, identifiers, stamp, raw, source, attrs,
                       removed=removed, address=address, modify=modify, release=release)
