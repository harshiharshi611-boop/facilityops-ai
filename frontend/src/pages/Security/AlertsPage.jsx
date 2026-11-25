// AlertsPage.jsx - Security tab 2: agent alerts, event log and investigation (Milestone 3)
import React, { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { secApi } from "../../m3/m3api.js";
import { useApi } from "../../m3/m3hooks.js";
import { Async, DataTable, KpiCard, Panel, SeverityBadge } from "../../m3/m3components.jsx";
import M3Page from "../../m3/M3Page.jsx";

const pretty = (t) => t.replace(/_/g, " ");

function Investigation({ eventId, onClose }) {
  const inv = useApi(() => secApi.investigate(eventId), [eventId]);
  return (
    <Panel title={`Investigation: event #${eventId}`} right={<button className="m3-btn" onClick={onClose}>Close</button>}>
      <Async state={inv}>
        {(d) => (
          <>
            <p><SeverityBadge severity={d.event.severity} /> <b>{pretty(d.event.event_type)}</b> at {d.event.zone}, {d.event.timestamp}
              {d.event.badge_id ? ` (badge ${d.event.badge_id})` : ""}</p>
            <p className="m3-note">{d.event.description}</p>
            {d.alert ? (
              <div className="m3-alert">
                <div><b>Recommended action:</b> {d.alert.recommended_action}</div>
                <div><b>Escalate to:</b> {d.alert.escalate_to}</div>
              </div>
            ) : null}
            {d.badge_timeline.length > 0 ? (
              <>
                <h4>Badge timeline (3 hours around the event)</h4>
                <DataTable rows={d.badge_timeline} columns={[
                  { key: "timestamp", label: "Time" }, { key: "zone", label: "Zone" },
                  { key: "direction", label: "Direction" }, { key: "result", label: "Result" }]} />
              </>
            ) : null}
            <h4>Badge swipes at this door (10 minutes around the event)</h4>
            <DataTable rows={d.door_swipes} empty="No badge swipes at this door around that time." columns={[
              { key: "timestamp", label: "Time" }, { key: "badge_id", label: "Badge" },
              { key: "direction", label: "Direction" }, { key: "result", label: "Result" }]} />
            <h4>Nearby CCTV events (30 minutes)</h4>
            <DataTable rows={d.cctv_nearby} empty="No CCTV events nearby." columns={[
              { key: "timestamp", label: "Time" }, { key: "event_type", label: "Event" },
              { key: "persons_detected", label: "People" }, { key: "duration_min", label: "Minutes" }]} />
          </>
        )}
      </Async>
    </Panel>
  );
}

export default function AlertsPage() {
  const { facilityId } = useOutletContext();
  const [severity, setSeverity] = useState("");
  const [sel, setSel] = useState({ f: null, id: null });          // remembers which facility the event belongs to
  const eventId = sel.f === facilityId ? sel.id : null;

  const summary = useApi(() => secApi.summary(facilityId), [facilityId]);
  const alerts = useApi(() => secApi.alerts(facilityId), [facilityId]);
  const events = useApi(() => secApi.events(facilityId, severity), [facilityId, severity]);

  return (
    <M3Page>
      <Async state={summary}>
        {(s) => (
          <div className="m3-kpis">
            <KpiCard label="Open alerts" value={s.open_alerts_total} sub="from the Security Agent" tone="amber" />
            <KpiCard label="Critical events" value={s.events_by_severity.Critical} sub="all 90 days" tone="red" />
            <KpiCard label="High events" value={s.events_by_severity.High} sub="all 90 days" tone="amber" />
          </div>
        )}
      </Async>

      <Panel title="Alerts" note="From the Security Agent (last 14 days of the data). Recorded here, not yet sent by email or SMS.">
        <Async state={alerts}>
          {(list) => list.length === 0
            ? <div className="m3-empty">No alerts yet. Run: python security_agent.py</div>
            : <div className="m3-alerts">{list.map((a) => (
              <div className="m3-alert" key={a.alert_id}>
                <div className="m3-alert-top"><SeverityBadge severity={a.severity} /><b>{a.title}</b></div>
                <div>{a.message}</div>
                <div className="m3-alert-action">Action: {a.recommended_action}</div>
                <div className="m3-alert-meta">Escalate to: {a.escalate_to}</div>
                <div className="m3-alert-meta">Evidence: {a.evidence}</div>
              </div>))}</div>}
        </Async>
      </Panel>

      <Panel title="Event log" note="Tap Investigate to see the badge timeline, door swipes and CCTV around an event."
        right={<select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">All severities</option><option>Critical</option><option>High</option>
          <option>Medium</option><option>Low</option></select>}>
        <Async state={events}>
          {(rows) => (
            <DataTable rows={rows} columns={[
              { key: "timestamp", label: "Time" },
              { key: "event_type", label: "Type", render: (r) => pretty(r.event_type) },
              { key: "severity", label: "Severity", render: (r) => <SeverityBadge severity={r.severity} /> },
              { key: "zone", label: "Zone" }, { key: "badge_id", label: "Badge" },
              { key: "go", label: "", render: (r) => <button className="m3-btn" onClick={() => setSel({ f: facilityId, id: r.event_id })}>Investigate</button> }]} />
          )}
        </Async>
      </Panel>

      {eventId ? <Investigation eventId={eventId} onClose={() => setSel({ f: null, id: null })} /> : null}
    </M3Page>
  );
}