// SecurityOverviewPage.jsx - Security tab 1: overview of events and door access (Milestone 3)
import React from "react";
import { useOutletContext } from "react-router-dom";
import { secApi } from "../../m3/m3api.js";
import { useApi } from "../../m3/m3hooks.js";
import { Async, BarList, DataTable, KpiCard, LineChart, Panel } from "../../m3/m3components.jsx";
import M3Page from "../../m3/M3Page.jsx";

const sevColor = { Critical: "var(--m3-red)", High: "var(--m3-amber)", Medium: "var(--m3-teal)", Low: "var(--m3-navy)" };
const pretty = (t) => t.replace(/_/g, " ");

export default function SecurityOverviewPage() {
  const { facilityId } = useOutletContext();
  const summary = useApi(() => secApi.summary(facilityId), [facilityId]);
  const visitors = useApi(() => secApi.visitors(facilityId), [facilityId]);
  const types = useApi(() => secApi.eventTypes(facilityId), [facilityId]);
  const timeline = useApi(() => secApi.timeline(facilityId), [facilityId]);
  const access = useApi(() => secApi.accessStats(facilityId), [facilityId]);

  return (
    <M3Page>
      <Async state={summary}>
        {(s) => (
          <div className="m3-kpis">
            <KpiCard label="Security events" value={s.events_total} sub={`last: ${s.last_event || "none"}`} tone="navy" />
            <KpiCard label="Critical" value={s.events_by_severity.Critical} sub={`${s.events_by_severity.High} high`} tone="red" />
            <KpiCard label="Open alerts" value={s.open_alerts_total} sub="from the Security Agent" tone="amber" />
            <KpiCard label="Denied swipes" value={`${s.denied_rate_pct}%`} sub={`${s.denied_swipes} of ${s.badge_swipes}`} tone="teal" />
            <KpiCard label="Visitors flagged" value={visitors.data ? visitors.data.flagged : "-"} sub={`of ${s.visitors} visitors`} tone="navy" />
          </div>
        )}
      </Async>

      <Panel title="Events by type">
        <Async state={types}>
          {(rows) => <BarList max={Math.max(1, ...rows.map((r) => r.count))} unit=""
            items={rows.map((r) => ({ label: pretty(r.event_type), value: r.count, color: sevColor[r.severity] }))} />}
        </Async>
      </Panel>

      <Panel title="Events per day" note="Orange line = critical events.">
        <Async state={timeline}>
          {(rows) => {
            if (rows.length === 0) return <div className="m3-empty">No events.</div>;
            const ticks = rows.map((r, i) => ({ i, label: r.date.slice(5) })).filter((t) => t.i % Math.ceil(rows.length / 6) === 0);
            return <LineChart xTicks={ticks} height={180} series={[
              { name: "All events", color: "var(--m3-navy)", values: rows.map((r) => r.count) },
              { name: "Critical", color: "var(--m3-amber)", values: rows.map((r) => r.critical) }]} />;
          }}
        </Async>
      </Panel>

      <Panel title="Door access by zone">
        <Async state={access}>
          {(rows) => (
            <DataTable rows={rows} columns={[
              { key: "zone", label: "Zone" }, { key: "swipes", label: "Swipes" },
              { key: "denied", label: "Denied" }, { key: "denied_rate_pct", label: "Denied %" }]} />
          )}
        </Async>
      </Panel>
    </M3Page>
  );
}