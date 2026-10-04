"""Conservative PDU correlation for normalized adapter evidence."""


def observe_pdu(engine, module, identifiers, stamp, raw, source, attrs,
                removed=False, address=False, modify=False, release=False):
    """Apply normalized PDU evidence; adapters supply attributes, never guessed IDs."""
    imsi = identifiers.get('imsi')
    # PDU evidence must explicitly name a UE. Never fall back to the most recent UE.
    owners = [r for r in engine.latest_identities() if imsi and r['imsi'] == imsi]
    if len(owners) != 1:
        engine.unresolved(stamp, raw, 'PDU evidence has no uniquely identified registration')
        return True
    owner = owners[0]
    engine.observe_network_function(owner, module)
    psi = attrs.get('pduSessionId')
    if removed or release:
        # Release may arrive after the same UE starts another registration. Search
        # existing sessions across attempts rather than assigning it to the latest.
        matching = [(r, s) for r in engine.attempts if r['imsi'] == imsi
                    for s in r['pduSessions'] if s['state'] != 'RELEASED' and all(
                        value is None or s.get(key) is None or s[key] == value
                        for key, value in attrs.items())]
        if len(matching) > 1:
            engine.unresolved(stamp, raw, 'Release matches multiple PDU sessions across attempts')
            return True
        if matching:
            owner = matching[0][0]
    candidates = [s for s in owner['pduSessions'] if s['state'] != 'RELEASED' and all(
        value is None or s.get(key) is None or s[key] == value for key, value in attrs.items())]
    exact = [s for s in candidates if psi is not None and s['pduSessionId'] == psi and all(
            v is None or s.get(k) is None or s[k] == v for k, v in attrs.items())]
    if exact:
        candidates = exact
    if len(candidates) > 1:
        engine.unresolved(stamp, raw, 'PDU evidence matches multiple sessions for this UE')
        return True
    session = candidates[0] if candidates else None
    if session is None:
        # A release/modify after removal must not resurrect a historical session.
        historical = [s for s in owner['pduSessions'] if psi is not None and s['pduSessionId'] == psi and all(
            v is None or s.get(k) is None or s[k] == v for k, v in attrs.items())]
        if (release or modify or removed) and historical:
            session = historical[-1]
        else:
            session = {'id': f"{owner['sessionId']}-pdu-{len(owner['pduSessions']) + 1}",
                       'pduSessionId': None, 'dnn': None, 'ipv4': None, 'ipv6': None,
                       'sst': None, 'sd': None, 'state': 'CONTEXT_OBSERVED',
                       'firstObservedAt': stamp.isoformat(timespec='milliseconds'),
                       'ipAssignedAt': None, 'releasedAt': None, 'events': []}
            owner['pduSessions'].append(session)
    session.update({k: v for k, v in attrs.items() if v is not None})
    kind = 'PDU_CONTEXT_OBSERVED'
    if address:
        kind = 'PDU_ADDRESS_OBSERVED'
        if session['ipv4'] or session['ipv6']:
            session.update(state='IP_ASSIGNED', ipAssignedAt=stamp.isoformat(timespec='milliseconds'))
    elif removed:
        kind = 'PDU_SESSION_REMOVED'
        session.update(state='RELEASED', releasedAt=stamp.isoformat(timespec='milliseconds'))
    elif modify:
        kind = 'PDU_CONTEXT_IDENTIFIED'
    elif release:
        kind = 'PDU_SM_CONTEXT_RELEASE_OBSERVED'
    engine.event(kind, stamp, raw, source, owner, session)
    return True
