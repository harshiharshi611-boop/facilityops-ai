// ForecastPage.jsx - Occupancy tab 2: 7-day forecast and how accurate it is (Milestone 3)
import React, { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { occApi } from "../../m3/m3api.js";
import { useApi } from "../../m3/m3hooks.js";
import { Async, DataTable, KpiCard, LineChart, Panel } from "../../m3/m3components.jsx";
import M3Page from "../../m3/M3Page.jsx";

export default function ForecastPage() {
  const { facilityId } = useOutletContext();
  const [pick, setPick] = useState({ f: null, zone: null });     // remembers which facility the zone belongs to

  const zones = useApi(() => occApi.zones(facilityId), [facilityId]);
  const fmetrics = useApi(() => occApi.forecastMetrics(facilityId), [facilityId]);

  const zoneList = zones.data ? zones.data.map((z) => z.zone) : [];
  const defaultZone = zones.data ? (zones.data.find((z) => z.status !== "Restricted") || zones.data[0]).zone : null;
  const zoneSel = pick.f === facilityId && pick.zone ? pick.zone : defaultZone;
  const forecast = useApi(() => (zoneSel ? occApi.forecast(facilityId, zoneSel) : Promise.resolve(null)), [facilityId, zoneSel]);

  return (
    <M3Page>
      <Async state={fmetrics}>
        {(m) => {
          const gb = m.models.find((x) => x.model.startsWith("Gradient"));
          const avg = m.models.find((x) => x.model.startsWith("Hour-of-week"));
          const meeting = m.zones.filter((z) => z.accuracy_pct >= m.target_pct).length;
          return (
            <div className="m3-kpis">
              <KpiCard label="ML forecast accuracy" value={`${gb.accuracy_pct.toFixed(1)}%`} sub="Gradient Boosting, unseen data" tone={gb.accuracy_pct >= m.target_pct ? "teal" : "red"} />
              <KpiCard label="Simple average" value={`${avg.accuracy_pct.toFixed(1)}%`} sub="usual value for that hour" tone="navy" />
              <KpiCard label="Target" value={`${m.target_pct}%`} sub="project requirement" tone="amber" />
              <KpiCard label="Zones meeting target" value={`${meeting} of ${m.zones.length}`} sub="in this facility" tone="navy" />
            </div>
          );
        }}
      </Async>

      <Panel title="7-day forecast" note="Forecast for the 7 days after the end of the data (the data is simulated)."
        right={<select value={zoneSel || ""} onChange={(e) => setPick({ f: facilityId, zone: e.target.value })}>
          {zoneList.map((z) => <option key={z}>{z}</option>)}</select>}>
        <Async state={forecast}>
          {(f) => {
            if (!f) return <div className="m3-empty">Choose a zone.</div>;
            const a = f.actual.map((r) => r.occupancy_count);
            const p = f.forecast.map((r) => r.predicted_count);
            const ts = [...f.actual.map((r) => r.timestamp), ...f.forecast.map((r) => r.timestamp)];
            const ticks = ts.map((t, i) => ({ i, label: t.slice(5, 10) })).filter((t) => t.i % 24 === 0);
            return (
              <LineChart hline={{ value: f.capacity, label: `capacity ${f.capacity}` }} xTicks={ticks}
                series={[{ name: "Actual (last 7 days)", color: "var(--m3-navy)", values: [...a, ...Array(p.length).fill(null)] },
                  { name: "Forecast (next 7 days)", color: "var(--m3-teal)", dashed: true, values: [...Array(a.length).fill(null), ...p] }]} />
            );
          }}
        </Async>
      </Panel>

      <Panel title="Forecast accuracy by zone" note="Accuracy = 100% minus the total error, measured on 27 days the model never saw.">
        <Async state={fmetrics}>
          {(m) => (
            <DataTable rows={m.zones} columns={[
              { key: "zone", label: "Zone" }, { key: "capacity", label: "Capacity" },
              { key: "accuracy_pct", label: "Accuracy %" }, { key: "mae_people", label: "Avg error (people)" },
              { key: "within_10pct_capacity", label: "Within 10% of capacity" },
              { key: "meets_target", label: "Meets 80%", render: (r) => (r.meets_target ? "Yes" : "No") }]} />
          )}
        </Async>
      </Panel>

      <Panel title="How reliable is this? (honest numbers)">
        <ul className="m3-honest">
          <li>Tested 7 days ahead, week by week, on 27 days the model never saw.</li>
          <li>A simple average is almost as accurate as the ML model, because the simulated data has regular daily patterns.</li>
          <li>Small zones such as the Server Room and ICU miss 80%: a few people of random change is a big percentage there.</li>
          <li>The forecast cannot predict sudden overcrowding. It is for planning space and staff, not for alarms.</li>
        </ul>
        <Async state={fmetrics}>
          {(m) => (
            <DataTable rows={m.models} columns={[
              { key: "model", label: "Model" }, { key: "accuracy_pct", label: "Accuracy %" },
              { key: "mae_people", label: "Avg error (people)" }, { key: "within_10pct_capacity", label: "Within 10% of capacity" }]} />
          )}
        </Async>
      </Panel>
    </M3Page>
  );
}