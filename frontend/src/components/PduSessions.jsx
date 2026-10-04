import React from "react";
import { Network } from "lucide-react";
import { Status, Fields, Empty } from "./Common";
export default function PduSessions({ sessions = [] }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>
            PDU sessions <span className="count">{sessions.length}</span>
          </h2>
        </div>
        <Network size={19} className="muted" />
      </div>
      {!sessions.length ? (
        <Empty
          icon={Network}
          title="No PDU session evidence"
          text="Session context, assigned IPs and SMF removal will appear when observed."
        />
      ) : (
        sessions.map((s) => (
          <article className="pdu-card" key={s.id}>
            <div className="pdu-title">
              <div className="pdu-name">
                <div>
                  <h3>Session {s.pduSessionId ?? "· ID not observed"}</h3>
                  <span className="muted small">
                    {s.dnn || "DNN not observed"}
                  </span>
                </div>
              </div>
              <Status state={s.state} />
            </div>
            <Fields
              fields={[
                ["IPv4 address", s.ipv4],
                ["IPv6 address", s.ipv6],
                [
                  "Slice SST / SD",
                  s.sst != null ? `${s.sst} / ${s.sd ?? "—"}` : null,
                ],
                ["First observed", s.firstObservedAt],
                ["IP assigned", s.ipAssignedAt],
                ["SMF removed", s.releasedAt],
              ]}
            />
          </article>
        ))
      )}
      <p className="footnote">
        <span className="info-dot">i</span>IP assignment is evidence, not proof
        of full establishment or working data traffic.
      </p>
    </section>
  );
}
