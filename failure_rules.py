"""Declarative registration-failure rules.

Patterns not documented as verified in README are deliberately conservative,
synthetic candidates that must be checked against real deployment logs.
"""
import re


FAILURE_RULES = (
    {
        # Verified against this deployment on 2026-09-07.
        'name': 'suci_not_found',
        'patterns': (r'\bCannot find SUCI\s*\[(\d+)\]',),
        'failure_stage': 'SUBSCRIBER_IDENTIFICATION',
        'reason': 'Core could not find the subscriber for the SUCI',
        'confidence': 'EXACT',
        'allowed_components': ('gmm',),
        'cause_patterns': (r'\bCannot find SUCI\s*\[(\d+)\]',),
    },
    {
        'name': 'registration_reject',
        'patterns': (r'\bRegistration reject(?:ed)?\b',),
        'failure_stage': 'REGISTRATION_COMPLETION',
        'reason': 'Registration rejected',
        'confidence': 'EXACT',
        'allowed_components': ('amf', 'gmm'),
        'cause_patterns': (
            r'\bcause\s*[:=]\s*\[?([^\],;]+)',
            r'\bRegistration reject(?:ed)?\s*[:\-]\s*([^\],;]+)',
            r'\bRegistration reject(?:ed)?\s*\[(\d+)\]',
        ),
    },
    {
        'name': 'authentication_mac_failure',
        'patterns': (r'\bMAC failure\b',),
        'failure_stage': 'AUTHENTICATION', 'reason': 'MAC failure',
        'confidence': 'EXACT', 'allowed_components': ('amf', 'gmm', 'ausf'),
    },
    {
        'name': 'authentication_failure',
        'patterns': (r'\bAuthentication (?:failure|failed|reject(?:ed)?)\b',
                     r'\bAuthentication response rejected\b'),
        'failure_stage': 'AUTHENTICATION', 'reason': 'Authentication failed',
        'confidence': 'EXACT', 'allowed_components': ('amf', 'gmm', 'ausf'),
    },
    {
        'name': 'nas_security_failure',
        'patterns': (r'\bSecurity mode (?:reject|failure)\b',
                     r'\bIntegrity check failed\b', r'\bNAS MAC verification failed\b'),
        'failure_stage': 'NAS_SECURITY', 'reason': 'NAS security failed',
        'confidence': 'EXACT', 'allowed_components': ('amf', 'gmm'),
    },
    {
        'name': 'subscriber_identification_failure',
        'patterns': (r'\bSubscriber not found\b', r'\bUnknown subscriber\b',
                     r'\bCannot find subscriber\b', r'\bUnknown UE\b(?!\s+by\s+SUCI)'),
        'failure_stage': 'SUBSCRIBER_IDENTIFICATION',
        'reason': 'Subscriber could not be identified or provisioned',
        'confidence': 'EXACT', 'allowed_components': ('amf', 'gmm', 'ausf', 'udm'),
    },
    {
        'name': 'ue_context_release_during_registration',
        'patterns': (r'\bUE context release(?:d)?\b', r'\bUEContextRelease\b'),
        'failure_stage': 'REGISTRATION_COMPLETION',
        'reason': 'UE context released before registration completed',
        'confidence': 'STAGE_LEVEL', 'allowed_components': ('amf', 'gmm'),
    },
)


def match_failure(component, line):
    """Return the first specific rule match and an optional protocol cause."""
    for rule in FAILURE_RULES:
        if component not in rule['allowed_components']:
            continue
        if not any(re.search(pattern, line, re.I) for pattern in rule['patterns']):
            continue
        cause = None
        for pattern in rule.get('cause_patterns', ()):
            match = re.search(pattern, line, re.I)
            if match:
                cause = match.group(1).strip(' []')
                break
        return rule, cause
    return None, None
