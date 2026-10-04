import React, { useState } from "react";
import { useInspector } from "./hooks/useInspector";
import { Status, Fields, Empty } from "./components/Common";
import Timeline from "./components/Timeline";
import PduSessions from "./components/PduSessions";
import UeList from "./components/UeList";
import FailureDetails from "./components/FailureDetails";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faCircleNodes,
  faClockRotateLeft,
  faShieldHalved,
  faArrowLeft,
} from "@fortawesome/free-solid-svg-icons";

const blank = {
  state: "WAITING",
  registrationStatus: "WAITING",
  events: [],
  pduSessions: [],
};
export default function App() {
  const { snapshot, error } = useInspector();
  const [selection, setSelection] = useState("");
  const [attempt, setAttempt] = useState("");
  const [query, setQuery] = useState("");
  const goHome = () => {
    setSelection("");
    setAttempt("");
  };
  const { health, attempts = [], ues = [] } = snapshot || {};
  // Anchor navigation to an observed attempt so SUCI → IMSI enrichment keeps
  // the same UE open. Never fall back to a different UE after a reader reset.
  const ue = ues.find((u) => u.sessionIds.includes(selection));
  const choices = ue
    ? attempts.filter((r) => ue.sessionIds.includes(r.sessionId))
    : [];
  const record =
    choices.find((r) => r.sessionId === attempt) || choices.at(-1) || blank;
  const connected = Boolean(health?.logSource.connected && !error);
  const sourceError = error || health?.logSource.error;
  const detection = health?.coreDetection;
  return (
    <>
      <header className="page-header">
        <div className="header-inner">
          <h1>
            <button
              className="app-home"
              aria-label="5G Core Inspector — Main screen"
              onClick={goHome}
            >
              <FontAwesomeIcon icon={faCircleNodes} /> 5G Core Inspector
            </button>
          </h1>
          <div className="source-status">
            <strong className={`connection ${connected ? "connected" : ""}`}>
              <i />
              {connected ? "Connected" : "Disconnected"}
            </strong>
            <span className="refresh-note">
              {detection?.label ? `${detection.label} · ` : ""}Updates every second
            </span>
          </div>
        </div>
      </header>
      <main>
        {sourceError && (
          <div className="notice danger" role="alert">
            <strong>
              {error ? "Inspector connection interrupted" : "Log source error"}
            </strong>
            <p>
              {sourceError}
              {error && " · Showing the last received snapshot."}
            </p>
          </div>
        )}
        {health?.linesProcessed === 0 && !sourceError && (
          <div className="notice">
            <strong>Waiting for core logs</strong>
            <p>
              UEs will appear when registration evidence arrives from the core.
            </p>
          </div>
        )}
        {detection?.status === "mixed" && (
          <div className="notice danger" role="alert">
            <strong>Multiple core formats detected</strong>
            <p>{detection.message}</p>
          </div>
        )}
        {detection?.status === "waiting" && health?.linesProcessed > 0 && !sourceError && (
          <div className="notice" role="status">
            <strong>Core not identified yet</strong>
            <p>{detection.message}</p>
          </div>
        )}
        {detection?.core === "oai" && (
          <div className="notice">
            <strong>OAI 5G Core detected</strong>
            <p>Enable AMF debug logs for registration details. Messages without a unique UE match remain uncorrelated.</p>
          </div>
        )}
        {!selection ? (
          <UeList
            ues={ues}
            attempts={attempts}
            query={query}
            onQuery={setQuery}
            onOpen={(u) => {
              setSelection(u.latestSessionId);
              setAttempt(u.latestSessionId);
            }}
          />
        ) : !ue ? (
          <section className="panel">
            <button className="back-button" onClick={goHome}>
              Back to UE list
            </button>
            <Empty
              title="UE no longer available"
              text="The selected attempt is absent from the current snapshot. Return to the UE list to select an observed UE."
            />
          </section>
        ) : (
          <>
            <button className="back-button" onClick={goHome}>
              <FontAwesomeIcon icon={faArrowLeft} /> All UEs
            </button>
            <div className="detail-heading">
              <div>
                <p className="muted">UE timeline</p>
                <h2 className="identity-value">{ue.identity}</h2>
              </div>
              <span className="muted">
                {choices.length} registration{" "}
                {choices.length === 1 ? "attempt" : "attempts"}
              </span>
            </div>
            <div className="selectors">
              <label>
                <span className="label-title">
                  <FontAwesomeIcon icon={faClockRotateLeft} /> Registration
                  attempt
                </span>
                <select
                  aria-label="Registration attempt"
                  value={record.sessionId || ""}
                  onChange={(e) => {
                    setAttempt(e.target.value);
                  }}
                >
                  {choices.length ? (
                    choices.map((r) => (
                      <option value={r.sessionId} key={r.sessionId}>
                        {r.sessionId} · {r.startedAt?.replace("T", " ")} ·{" "}
                        {r.state}
                      </option>
                    ))
                  ) : (
                    <option value="">No attempts</option>
                  )}
                </select>
              </label>
            </div>
            <section className="panel">
              <div className="panel-heading">
                <h2>
                  <FontAwesomeIcon icon={faShieldHalved} /> Registration
                </h2>
                <Status state={record.state} />
              </div>
              <div className="registration-result">
                <p>
                  Registration result:{" "}
                  <strong>{record.registrationStatus}</strong>
                </p>
                <p className="duration">
                  Duration: <strong>{record.durationMs ?? "—"} ms</strong>
                </p>
              </div>
              {record.state === "DEREGISTERED" && (
                <p className="explanation">
                  Deregistration request observed; the successful registration
                  result is preserved.
                </p>
              )}
              <Fields
                fields={[
                  ["SUCI", record.suci],
                  ["IMSI", record.imsi],
                  ["RAN UE NGAP ID", record.ranUeNgapId],
                  ["AMF UE NGAP ID", record.amfUeNgapId],
                  ["TAC", record.tac],
                  ["Cell ID", record.cellId],
                  ["Registration started", record.startedAt],
                  ["Registration completed", record.completedAt],
                  [
                    "Deregistration requested",
                    record.deregistrationRequestedAt,
                  ],
                ]}
              />
              {record.state === "FAILED" && (
                <FailureDetails key={record.sessionId} record={record} />
              )}
            </section>
            <Timeline key={record.sessionId} events={record.events} />
            <PduSessions sessions={record.pduSessions} />
          </>
        )}
      </main>
      <footer className="page-footer">
        <div className="footer-inner">
          <a className="footer-brand" href="https://systronlab.github.io/">
            SYSTRON LAB
          </a>
          <span>{detection?.label || "5G core"} log diagnostics</span>
        </div>
      </footer>
    </>
  );
}
