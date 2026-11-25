// IncidentsPage.jsx - Occupancy tab 3: overcrowding incidents and agent alerts (Milestone 3)
import React from "react";
import { useOutletContext } from "react-router-dom";
import { occApi } from "../../m3/m3api.js";
import { useApi } from "../../m3/m3hooks.js";
import { Async, DataTable, KpiCard, Panel, SeverityBadge } from "../../m3/m3components.jsx";
import M3Page from "../../m3/M3Page.jsx";

export default function IncidentsPage() {
  const { facilityId } = useOutletContext();
  const summary = useApi(() => occApi.summary(facilityId), [facilityId]);
  const alerts = useApi(() => occApi.alerts(facilityId), [facilityId]);
  const incidents = useApi(() => occApi.incidents(facilityId), [facilityId]);

  return (
    <M3Page>
      <Async state={summary}>
        {(s) => (
          <div className="m3-kpis">
            <KpiCard label="Overcrowding incidents" value={s.facility.overcrowding_incidents} sub="over capacity, all 90 days" tone="amber" />
            <KpiCard label="Open alerts" value={s.open_alerts_total} sub="from the Occupancy Agent" tone="navy" />
            <KpiCard label="Planted events found" value={s.detection ? `${s.detection.events_found} of ${s.detection.planted_events}` : "-"} sub="both facilities together" tone="teal" />
          </div>
        )}
      </Async>

      <Panel title="Occupancy alerts" note="From the Occupancy Agent. Recorded here, not yet sent by email or SMS.">
        <Async state={alerts}>
          {(list) => list.length === 0
            ? <div className="m3-empty">No alerts yet. Run: python occupancy_agent.py</div>
            : <div className="m3-alerts">{list.map((a) => (
              <div className="m3-alert" key={a.alert_id}>
                <div className="m3-alert-top"><SeverityBadge severity={a.severity} /><b>{a.title}</b></div>
                <div>{a.message}</div>
                <div className="m3-alert-action">Action: {a.recommended_action}</div>
              </div>))}</div>}
        </Async>
      </Panel>

      <Panel title="Overcrowding incidents" note="Latest 20 times a zone held more people than its capacity.">
        <Async state={incidents}>
          {(rows) => (
            <DataTable rows={rows} columns={[
              { key: "start_time", label: "Start" }, { key: "zone", label: "Zone" },
              { key: "hours", label: "Hours" },
              { key: "peak", label: "Peak", render: (r) => `${r.peak_count}/${r.capacity} (${r.peak_utilization}%)` },
              { key: "severity", label: "Severity", render: (r) => <SeverityBadge severity={r.severity} /> }]} />
          )}
        </Async>
      </Panel>

      <Panel title="How reliable is this? (honest numbers)">
        <Async state={summary}>
          {(s) => (
            <ul className="m3-honest">
              {s.detection ? <li>Overcrowding detection found {s.detection.events_found} of {s.detection.planted_events} planted events.
                Precision is {s.detection.precision_pct}% because {s.detection.false_incidents} flagged peaks were natural, not planted.</li> : null}
              <li>An incident means more people than capacity. A near-full early warning at 90% would flag far too many hours.</li>
              <li>Alerts cover the last 14 days of the data. All data is simulated.</li>
            </ul>
          )}
        </Async>
      </Panel>
    </M3Page>
  );
}