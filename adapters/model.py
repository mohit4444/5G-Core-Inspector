"""Vendor-neutral identifiers and diagnostic fields shared by adapters."""
IDENTIFIER_FIELDS = ('ranUeNgapId', 'amfUeNgapId', 'tac', 'cellId', 'suci', 'imsi')
DIAGNOSTIC_DEFAULTS = {
    'lastSuccessfulStage': None, 'failureStage': None, 'failureReason': None,
    'protocolCause': None, 'diagnosisConfidence': None, 'failureEvidence': None,
    'failedAt': None,
}
