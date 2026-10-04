import React from "react";
import { Search, ChevronRight } from "lucide-react";
import { Empty, Status } from "./Common";

export default function UeList({ ues, attempts, query, onQuery, onOpen }) {
  const search = query.trim().toLowerCase();
  const shown = ues.filter((ue) => {
    const records = attempts.filter((r) => ue.sessionIds.includes(r.sessionId));
    return [
      ue.identity,
      ue.imsi,
      ue.suci,
      ...records.flatMap((r) => [
        r.imsi,
        r.suci,
        r.sessionId,
        r.ranUeNgapId,
        r.amfUeNgapId,
      ]),
    ]
      .filter((v) => v != null)
      .join(" ")
      .toLowerCase()
      .includes(search);
  });
  return (
    <section className="panel ue-list-panel">
      <div className="panel-heading">
        <div>
          <h2>
            UE list <span className="count">{ues.length}</span>
          </h2>
          <p className="muted">
            Select a UE to inspect its registration attempts and timeline.
          </p>
        </div>
      </div>
      <label className="search">
        <Search size={16} />
        <input
          aria-label="Search UEs"
          placeholder="Search identity, NGAP ID or attempt…"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
        />
      </label>
      <p className="list-count muted" role="status">
        {shown.length} of {ues.length} UEs
      </p>
      {shown.length ? (
        <ul className="ue-list">
          {shown.map((ue) => {
            const latest = attempts.find(
              (r) => r.sessionId === ue.latestSessionId,
            );
            return (
              <li key={ue.identity}>
                <button
                  className="ue-row"
                  onClick={() => onOpen(ue)}
                  aria-label={`Open ${ue.identity}`}
                >
                  <span className="ue-summary">
                    <strong className="identity-value">{ue.identity}</strong>
                    {ue.suci && ue.suci !== ue.identity && (
                      <span className="muted ue-alias">{ue.suci}</span>
                    )}
                    <span className="muted">
                      {ue.sessionIds.length}{" "}
                      {ue.sessionIds.length === 1 ? "attempt" : "attempts"} ·
                      Latest start:{" "}
                      {latest?.startedAt?.replace("T", " ") || "Not observed"}
                    </span>
                  </span>
                  <span className="ue-row-status">
                    <span className="muted">Latest attempt</span>
                    <Status state={ue.state} />
                  </span>
                  <ChevronRight size={18} aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <Empty
          title={ues.length ? "No matching UEs" : "Waiting for UE detection"}
          text={
            ues.length
              ? "Try another identity, NGAP ID or registration attempt."
              : "UEs will appear here when the core logs show a registration attempt."
          }
        />
      )}
    </section>
  );
}
