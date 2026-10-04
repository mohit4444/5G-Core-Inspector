import React, { useState } from "react";
import { Search, Activity, ArrowDown } from "lucide-react";
import { Evidence, Empty, readable } from "./Common";
export default function Timeline({ events = [] }) {
  const [query, setQuery] = useState("");
  const shown = events.filter((e) =>
    `${readable(e.type)} ${e.type} ${e.rawEvidence || ""}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <section className="panel timeline-panel">
      <div className="panel-heading">
        <div>
          <h2>
            Event timeline <span className="count">{events.length}</span>
          </h2>
        </div>
        <span className="muted small">
          <ArrowDown size={13} /> Oldest first
        </span>
      </div>
      <label className="search">
        <Search size={16} />
        <input
          aria-label="Search events"
          placeholder="Search events or raw evidence…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {shown.length ? (
        <ol className="timeline">
          {shown.map((e) => (
            <li
              key={`${e.sessionId}-${e.type}-${e.timestamp}-${e.rawEvidence}`}
            >
              <span className={`event-marker event-${e.state}`} />
              <div className="event-head">
                <h3>{readable(e.type).toLowerCase()}</h3>
                <time>{e.timestamp?.replace("T", " ")}</time>
              </div>
              <div className="event-meta">
                <span>{e.sessionId}</span>
                <span>{readable(e.state)}</span>
              </div>
              {e.pduSession && (
                <p className="event-pdu">
                  PDU {e.pduSession.pduSessionId ?? "ID unknown"} <b>·</b>{" "}
                  {e.pduSession.dnn ?? "DNN unknown"} <b>·</b>{" "}
                  {readable(e.pduSession.state)}
                </p>
              )}
              <Evidence raw={e.rawEvidence} />
            </li>
          ))}
        </ol>
      ) : (
        <Empty
          icon={Activity}
          title={query ? "No matching events" : "Listening for evidence"}
          text={
            query
              ? "Try another event name or log message."
              : "Observed registration and PDU events will appear here."
          }
        />
      )}
    </section>
  );
}
