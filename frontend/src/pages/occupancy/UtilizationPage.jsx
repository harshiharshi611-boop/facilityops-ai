// UtilizationPage.jsx - Occupancy tab 1: how full is each zone? (Milestone 3)
import React, { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { occApi } from "../../m3/m3api.js";
import { useApi } from "../../m3/m3hooks.js";
import { Async, BarList, DataTable, Heatmap, KpiCard, Panel, StatusBadge } from "../../m3/m3components.jsx";
import M3Page from "../../m3/M3Page.jsx";

const statusColor = { "Over capacity": "var(--m3-red)", "Near full": "var(--m3-amber)", Normal: "var(--m3-teal)" };

export default function UtilizationPage() {
  const { facilityId } = useOutletContext();
  const [dayType, setDayType] = useState("Weekday");

  const summary = useApi(() => occApi.summary(facilityId), [facilityId]);
  const current = useApi(() => occApi.current(facilityId), [facilityId]);
  const heat = useApi(() => occApi.heatmap(facilityId, dayType), [facilityId, dayType]);
  const zones = useApi(() => occApi.zones(facilityId), [facilityId]);

  return (
    <M3Page>
      <Async state={summary}>
        {(s) => (
          <div className="m3-kpis">
            <KpiCard label="Occupancy rate" value={`${s.facility.occupancy_rate}%`} sub="weekdays 08:00-19:00" tone="navy" />
            <KpiCard label="Peak hour" value={`${String(s.facility.peak_hour).padStart(2, "0")}:00`} sub="busiest time of day" tone="teal" />
            <KpiCard label="Most used zone" value={s.facility.most_used_zone} sub="highest busy-hours fill" tone="amber" />
            <KpiCard label="Least used zone" value={s.facility.least_used_zone} sub="lowest busy-hours fill" tone="navy" />
            <KpiCard label="Underused zones" value={s.facility.underused_zones} sub="below 35% in busy hours" tone="teal" />
          </div>
        )}
      </Async>

      <Panel title="Right now" note={current.data ? `Latest hour in the data: ${current.data.as_of}` : ""}>
        <Async state={current}>
          {(c) => (
            <BarList max={120} items={c.zones.map((z) => ({
              label: z.zone, value: z.utilization, text: `${z.occupancy_count}/${z.capacity} (${z.utilization}%)`,
              color: statusColor[z.status] }))} />
          )}
        </Async>
      </Panel>

      <Panel title="Occupancy heatmap" note="Average % of capacity for each hour of the day."
        right={<select value={dayType} onChange={(e) => setDayType(e.target.value)}>
          <option>Weekday</option><option>Weekend</option></select>}>
        <Async state={heat}>{(h) => <Heatmap data={h} />}</Async>
      </Panel>

      <Panel title="Zones" note="Utilization is measured on weekdays 08:00-19:00.">
        <Async state={zones}>
          {(rows) => (
            <DataTable rows={rows} columns={[
              { key: "zone", label: "Zone" }, { key: "capacity", label: "Capacity" },
              { key: "busy_hours_utilization", label: "Busy-hours %" }, { key: "peak_utilization", label: "Peak %" },
              { key: "hours_over_capacity", label: "Hours over" },
              { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> }]} />
          )}
        </Async>
      </Panel>
    </M3Page>
  );
}