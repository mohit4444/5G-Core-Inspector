"""Evidence-only registration rules with conservative multi-UE correlation."""
import copy
import re
import time
from adapters import open5gs, oai
from adapters.model import IDENTIFIER_FIELDS, DIAGNOSTIC_DEFAULTS
from datetime import datetime, timedelta

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
NETWORK_FUNCTIONS = {'amf': 'AMF', 'gmm': 'AMF', 'ausf': 'AUSF',
                     'udm': 'UDM', 'smf': 'SMF'}


class Inspector:
    def __init__(self, year=None, timeout=30):
        self.year = year or datetime.now().year
        self.timeout = timeout
        self.attempts = []
        self.events = []
        self.seen = set()
        self.lines = 0
        self.clocks = {}
        self.uncorrelated = []
        self.adapter = None
        self.detected = set()
        self.adapter_state = {}

    @property
    def active(self):
        return any(self.is_active(record) for record in self.attempts)

    @staticmethod
    def is_active(record):
        return record['state'] in ('UE_DETECTED', 'REGISTRATION_IN_PROGRESS')

    def unresolved(self, stamp, raw, reason):
        self.uncorrelated.append({'timestamp': stamp.isoformat(timespec='milliseconds'),
                                  'rawEvidence': raw, 'reason': reason})

    @staticmethod
    def observe_network_function(record, component):
        """Record only a component from evidence correlated to this attempt."""
        network_function = NETWORK_FUNCTIONS.get(component)
        if network_function and network_function not in record['networkFunctions']:
            record['networkFunctions'].append(network_function)

    def correlate(self, identifiers, candidates, allow_enrichment=False):
        # Known identity / AMF ID outrank RAN ID (RAN IDs can be reused).
        keys = [k for k in ('imsi', 'suci', 'amfUeNgapId', 'ranUeNgapId') if k in identifiers]
        compatible = [r for r in candidates if all(
            r[k] is None or r[k] == identifiers[k] for k in keys)]
        for key in keys:
            matches = [r for r in compatible if r[key] == identifiers[key]]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                compatible = matches
        if allow_enrichment and len(compatible) == 1:
            return compatible[0]
        return None

    def latest_identities(self):
        ids = {group['latestSessionId'] for group in self.ues()}
        return [r for r in self.attempts if r['sessionId'] in ids]

    def ues(self):
        aliases = {}
        for record in self.attempts:
            if record['suci'] and record['imsi']:
                aliases.setdefault(record['suci'], set()).add(record['imsi'])
        groups = {}
        for record in self.attempts:
            known = aliases.get(record['suci'], set())
            resolved = next(iter(known)) if len(known) == 1 else None
            identity = record['imsi'] or resolved or record['suci'] or record['sessionId']
            group = groups.setdefault(identity, {'identity': identity, 'sessionIds': []})
            group.update(latestSessionId=record['sessionId'], state=record['state'],
                         imsi=record['imsi'] or resolved, suci=record['suci'])
            group['sessionIds'].append(record['sessionId'])
        return copy.deepcopy(list(groups.values()))

    def snapshot(self):
        return copy.deepcopy(self.attempts[-1]) if self.attempts else {
            'sessionId': None, 'state': 'WAITING', 'registrationStatus': 'WAITING',
            **dict.fromkeys(IDENTIFIER_FIELDS), 'startedAt': None, 'completedAt': None,
            'durationMs': None, **DIAGNOSTIC_DEFAULTS,
            'deregistrationRequestedAt': None, 'networkFunctions': [],
            'pduSessions': [], 'events': []}

    def event(self, kind, stamp, raw, timestamp_source='log', record=None, pdu=None):
        record = record if record is not None else self.attempts[-1]
        event = {'type': kind, 'timestamp': stamp.isoformat(timespec='milliseconds'),
                 'timestampSource': timestamp_source, 'sessionId': record['sessionId'],
                 'core': record.get('core'), 'state': record['state'], 'registrationStatus': record['registrationStatus'],
                 'identifiers': {key: record[key] for key in IDENTIFIER_FIELDS}, 'rawEvidence': raw}
        if kind == 'REGISTRATION_FAILED':
            event.update({key: copy.deepcopy(record[key]) for key in DIAGNOSTIC_DEFAULTS})
            event['durationMs'] = record['durationMs']
        if pdu is not None:
            event['pduSession'] = {k: v for k, v in pdu.items() if k != 'events'}
            pdu['events'].append(copy.deepcopy(event))
        record['events'].append(event)
        self.events.append(event)

    def expire(self, stamp=None, clock=None):
        if len(self.detected) > 1:
            return
        for record in self.attempts:
            if not self.is_active(record):
                continue
            start = datetime.fromisoformat(record['startedAt'])
            elapsed = ((stamp - start).total_seconds() if stamp is not None else
                       (time.monotonic() if clock is None else clock) - self.clocks[record['sessionId']])
            if elapsed >= self.timeout:
                requested = record['lastSuccessfulStage'] == 'REGISTRATION_REQUEST_RECEIVED'
                self.fail(start + timedelta(seconds=self.timeout),
                          'AFTER_REGISTRATION_REQUEST' if requested else 'NGAP_NAS',
                          ('Registration did not complete before timeout' if requested else
                           'No Registration request observed before timeout'),
                          'STAGE_LEVEL', None, 'timer', record, 'registration_timeout')

    def fail(self, stamp, stage, reason, confidence, raw, source, record, rule_name,
             component=None, severity=None, cause=None, identifiers=None):
        evidence = None if raw is None else {
            'rawLogLine': raw, 'timestamp': stamp.isoformat(timespec='milliseconds'),
            'component': component, 'severity': severity, 'matchedRule': rule_name,
            'identifiers': copy.deepcopy(identifiers or {}),
            'extractedIdentity': next((identifiers[k] for k in ('imsi', 'suci', 'amfUeNgapId', 'ranUeNgapId')
                                      if identifiers and k in identifiers), None),
            'extractedCause': cause,
        }
        record.update(state='FAILED', registrationStatus='FAILED', failureStage=stage,
                      failureReason=reason, protocolCause=cause,
                      diagnosisConfidence=confidence, failureEvidence=evidence,
                      failedAt=stamp.isoformat(timespec='milliseconds'),
                      durationMs=round((stamp - datetime.fromisoformat(record['startedAt'])).total_seconds() * 1000))
        self.event('REGISTRATION_FAILED', stamp, raw, source, record)

    def start_attempt(self, stamp, raw, source, identifiers, clock=None,
                      kind='INITIAL_UE_MESSAGE'):
        record = {'sessionId': f'registration-{len(self.attempts) + 1}',
                  'core': self.adapter.KEY, 'state': 'UE_DETECTED',
                  'registrationStatus': 'IN_PROGRESS', **dict.fromkeys(IDENTIFIER_FIELDS),
                  'startedAt': stamp.isoformat(timespec='milliseconds'),
                  'completedAt': None, 'durationMs': None, **DIAGNOSTIC_DEFAULTS,
                  'deregistrationRequestedAt': None, 'networkFunctions': [],
                  'pduSessions': [], 'events': []}
        record.update(identifiers)
        self.attempts.append(record)
        self.clocks[record['sessionId']] = time.monotonic() if clock is None else clock
        record['lastSuccessfulStage'] = kind
        if kind == 'REGISTRATION_REQUEST_RECEIVED':
            record['state'] = 'REGISTRATION_IN_PROGRESS'
            kind = 'REGISTRATION_REQUESTED'
        self.event(kind, stamp, raw, source, record)
        return record

    def finish(self):
        """Finish a framed evidence block at EOF; EOF itself is not a timeout."""
        if self.adapter is oai and len(self.detected) == 1:
            oai.flush(self)

    def detection(self):
        conflict = len(self.detected) > 1
        return {'status': 'mixed' if conflict else 'detected' if self.adapter else 'waiting',
                'core': None if conflict or not self.adapter else self.adapter.KEY,
                'label': None if conflict or not self.adapter else self.adapter.LABEL,
                'adapterTarget': None if conflict or not self.adapter else self.adapter.TARGET,
                'observedCores': sorted(self.detected),
                'message': ('Both Open5GS and OAI log formats were observed. Analysis is paused. '
                            'Restart the Inspector with logs from one core deployment.' if conflict else
                            'Waiting for a supported Open5GS or OAI log format.' if not self.adapter else None)}

    def feed(self, raw, clock=None):
        self.lines += 1
        raw = raw.rstrip('\r\n')
        line = ANSI.sub('', raw)
        # Detect before parsing; container names and messages mentioning a vendor
        # are not signatures. A mixed stream never changes adapters mid-history.
        for adapter in (open5gs, oai):
            if adapter.detect(line):
                self.detected.add(adapter.KEY)
                if self.adapter is None:
                    self.adapter = adapter
        if len(self.detected) > 1:
            if raw not in self.seen:
                self.unresolved(datetime.now(), raw, self.detection()['message'])
                self.seen.add(raw)
            return
        if not self.adapter:
            return
        # OAI multiline context fields repeat across dumps; their framing supplies
        # identity and timestamps, so deduplication occurs at the evidence block.
        if self.adapter is open5gs:
            if raw in self.seen:
                return
            self.seen.add(raw)
        self.adapter.feed(self, raw, line, clock)
