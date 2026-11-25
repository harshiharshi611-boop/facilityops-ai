// VisitorsPage.jsx - Security tab 3: visitors and how reliable the detection is (Milestone 3)
import React from "react";
import { useOutletContext } from "react-router-dom";
import { secApi } from "../../m3/m3api.js";
import { useApi } from "../../m3/m3hooks.js";
import { Async, DataTable, KpiCard, Panel, StatusBadge } from "../../m3/m3components.jsx";
import M3Page from "../../m3/M3Page.jsx";

export default function VisitorsPage() {
  const { facilityId } = useOutletContext();
  const visitors = useApi(() => secApi.visitors(facilityId), [facilityId]);
  const evaluation = useApi(() => secApi.evaluation(), []);

  return (
    <M3Page>
      <Async state={visitors}>
        {(v) => (
          <div className="m3-kpis">
            <KpiCard label="Visitors" value={v.total} sub="all 90 days" tone="navy" />
            <KpiCard label="Flagged" value={v.flagged} sub="no check-out, overstay or restricted room" tone="red" />
            <KpiCard label="Average stay" value={`${v.avg_stay_hours} h`} sub="visitors with a check-out" tone="teal" />
          </div>
        )}
      </Async>

      <Panel title="Recent visitors">
        <Async state={visitors}>
          {(v) => (
            <>
              <p className="m3-note">Flagged: {v.flagged}
                {Object.entries(v.by_flag).filter(([k]) => k !== "Normal").map(([k, n]) => ` | ${k}: ${n}`).join("")}</p>
              <DataTable rows={v.recent} columns={[
                { key: "visitor_id", label: "Visitor" }, { key: "check_in", label: "Check-in" },
                { key: "zone_visited", label: "Zone" },
                { key: "stay_hours", label: "Stay (h)", render: (r) => r.stay_hours ?? "no check-out" },
                { key: "flag", label: "Flag", render: (r) => <StatusBadge status={r.flag} /> }]} />
            </>
          )}
        </Async>
      </Panel>

      <Panel title="How reliable is this? (honest numbers)">
        <Async state={evaluation}>
          {(e) => {
            const all = e.rules.find((r) => r.event_type === "ALL");
            return (
              <>
                <ul className="m3-honest">
                  {all ? <li>The rules found {all.found} of {all.planted} planted incidents with {all.false_alarms} false alarm(s), for both facilities together.</li> : null}
                  <li>The incidents are simulated and clean, so real-world scores would be lower. Treat these numbers as an upper bound.</li>
                  <li>Three rules were fixed after the first test run.</li>
                  <li>The Isolation Forest (ML) found far fewer badge incidents than the rules, so the rules are the main detector.</li>
                </ul>
                <DataTable rows={e.rules} columns={[
                  { key: "event_type", label: "Rule" }, { key: "planted", label: "Planted" },
                  { key: "detected", label: "Alerts" }, { key: "false_alarms", label: "False" },
                  { key: "recall_pct", label: "Recall %" }, { key: "precision_pct", label: "Precision %" }]} />
                <h4>ML comparison (Isolation Forest)</h4>
                <DataTable rows={e.ml} columns={[
                  { key: "event_type", label: "Incident" }, { key: "planted", label: "Planted" },
                  { key: "found_by_ml", label: "Found by ML" }, { key: "recall_pct", label: "Recall %" }]} />
              </>
            );
          }}
        </Async>
      </Panel>
    </M3Page>
  );
}