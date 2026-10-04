import React from "react";
import { Evidence, Fields, readable } from "./Common";

const guidance = {
  SUBSCRIBER_IDENTIFICATION: {
    causes: [
      "The subscriber record may be missing, or the UE identity may differ from the provisioned identity.",
    ],
    checks: [
      "Compare the observed UE identity with the intended subscriber record.",
      "Check subscriber provisioning and the correlated UDM/AUSF logs around this attempt.",
    ],
  },
  AUTHENTICATION: {
    causes: [
      "UE and subscriber authentication settings may differ, or the authentication exchange may have been interrupted.",
    ],
    checks: [
      "Compare the UE and core authentication configuration locally.",
      "Review correlated AMF/AUSF messages for the rejection or failure detail.",
    ],
  },
  NAS_SECURITY: {
    causes: [
      "UE and core security settings or security context may be inconsistent.",
    ],
    checks: [
      "Review the security-mode exchange and any reported integrity or algorithm error.",
      "Compare supported security settings on the UE and core.",
    ],
  },
  REGISTRATION_COMPLETION: {
    causes: [
      "The core may have rejected registration, or the UE context may have been released before completion. The reported reason alone may not identify the underlying cause.",
    ],
    checks: [
      "Review the observed reject or release message and its preceding correlated events.",
      "Use the originating component and message to interpret any cause value; do not assume codes share the same meaning across messages.",
    ],
  },
};
const timeoutGuidance = {
  causes: [
    "The UE or network may have stopped progressing, or relevant completion logs may be missing from the reader.",
  ],
  checks: [
    "Check that log collection covered the full attempt and stayed connected.",
    "Inspect messages after the last confirmed stage in the UE, radio and core logs, using matching identifiers.",
  ],
};
const unknownGuidance = {
  causes: ["The available evidence does not establish an underlying cause."],
  checks: [
    "Review the failure evidence and the last confirmed event for this attempt.",
    "Collect additional logs with matching identifiers before attributing a cause.",
  ],
};

export default function FailureDetails({ record }) {
  const coreLabel = record.core === "oai" ? "OAI 5G Core" : record.core === "open5gs" ? "Open5GS" : "core";
  const timer =
    !record.failureEvidence?.rawLogLine &&
    record.events?.some(
      (e) => e.type === "REGISTRATION_FAILED" && e.timestampSource === "timer",
    );
  const advice = timer
    ? timeoutGuidance
    : guidance[record.failureStage] || unknownGuidance;
  return (
    <div
      className={`failure-panel confidence-${record.diagnosisConfidence}`}
      role="region"
      aria-label="Registration failure details"
    >
      <h3>Registration failed</h3>
      <Fields
        fields={[
          ["Observed failure", record.failureReason || "Not provided by core"],
          [
            "Failed at",
            record.failureStage ? readable(record.failureStage) : "Unknown",
          ],
          [
            "Last confirmed stage",
            record.lastSuccessfulStage
              ? readable(record.lastSuccessfulStage)
              : "Not observed",
          ],
          ["Protocol cause", record.protocolCause ?? "Not provided by core"],
          [
            "Confidence",
            record.diagnosisConfidence === "EXACT"
              ? "Exact"
              : record.diagnosisConfidence === "STAGE_LEVEL"
                ? "Stage-level"
                : "Unknown",
          ],
          [
            "Duration",
            record.durationMs == null ? null : `${record.durationMs} ms`,
          ],
        ]}
      />
      {timer && (
        <p className="explanation">
          The Inspector timed out waiting for completion. No explicit core
          failure message was observed.
        </p>
      )}
      <div className="failure-guidance">
        <div>
          <h4>Possible causes</h4>
          <p className="muted">
            Hypotheses to investigate; not confirmed by this evidence.
          </p>
          <ul>
            {advice.causes.map((cause) => (
              <li key={cause}>{cause}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Suggested checks</h4>
          <ul>
            {advice.checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
        </div>
      </div>
      <Evidence
        raw={record.failureEvidence?.rawLogLine}
        label={timer ? "Timeout evidence" : `Evidence from ${coreLabel}`}
        sourceLabel={timer ? "INSPECTOR TIMER" : "ORIGINAL CORE LOG"}
        fallback={
          timer
            ? "Timer-generated timeout. No matching core failure log line."
            : "No raw failure log line available."
        }
      />
      {timer && record.events?.some((e) => e.rawEvidence) && (
        <Evidence
          raw={record.events.filter((e) => e.rawEvidence).at(-1).rawEvidence}
          label={`Last observed ${coreLabel} evidence`}
        />
      )}
    </div>
  );
}
