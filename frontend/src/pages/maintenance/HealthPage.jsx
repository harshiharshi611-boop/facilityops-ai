import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import * as api from "../../api";
import { useData } from "../../hooks";
import { Kpi, Card, Badge, ErrorBox } from "../../components";

const STATUS_COLOR = {
  Excellent: "#10b981", Good: "#2563eb", Warning: "#f59e0b", Critical: "#ef4444",
};
const FILTERS = ["All", "Critical", "Warning", "Good", "Excellent"];

export default function HealthPage() {
  const { facilityId } = useOutletContext();
  const [filter, setFilter] = useState("All");
  const { data, error } = useData(
    () => Promise.all([
      api.getMaintSummary(facilityId),
      api.getMaintAssets(facilityId),
      api.getHealthByType(facilityId),
      api.getMaintEvents(facilityId),
    ]),
    [facilityId]
  );

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data) return <p>Loading...</p>;

  const [summary, assets, byType, events] = data;
  const k = summary.kpis;
  const rows = filter === "All"
    ? assets.items
    : assets.items.filter((a) => a.status === filter);

  return (
    <>
      <div className="grid kpis">
        <Kpi label="Assets monitored" value={k.assets_monitored} sub="in this facility" />
        <Kpi label="Average health" value={`${k.avg_health}/100`} sub="all machines" />
        <Kpi label="Predicted failures" value={k.predicted_failures} sub="within 14 days" />
        <Kpi label="Open work orders" value={k.open_work_orders}
             sub={`${k.critical_alerts} critical alert(s)`} />
        <Kpi label="Overdue services" value={k.overdue_services} sub="past their interval" />
        <Kpi label="Downtime avoidable" value={`${k.downtime_avoided_hours} h`}
             sub="potential, if serviced in time" />
      </div>

      <div className="grid two">
        <Card title="Equipment health distribution">
          {summary.distribution.map((d) => (
            <div className="barrow" key={d.status}>
              <span>{d.status}</span>
              <div className="bartrack">
                <div className="barfill"
                     style={{ width: `${d.percent}%`, background: STATUS_COLOR[d.status] }} />
              </div>
              <span className="muted">{d.machines} ({d.percent}%)</span>
            </div>
          ))}
          <p className="muted">
            Score bands: Excellent 85+, Good 70-84, Warning 50-69, Critical below 50.
          </p>
        </Card>

        <Card title="Average health by equipment type">
          <div className="chart">
            <ResponsiveContainer>
              <BarChart data={byType.items} layout="vertical" margin={{ left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey="asset_type" width={110} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="avg_health" fill="#2563eb" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid">
        <Card title="Active abnormal behavior (still happening)">
          {events.items.length === 0 ? (
            <p className="muted">No machine is behaving abnormally right now.</p>
          ) : (
            events.items.map((e) => (
              <div className="list-row" key={e.event_id}>
                <Badge kind={e.severity}>{e.severity}</Badge>
                <div>
                  <b>{e.asset_name}</b> <span className="muted">({e.asset_type})</span>
                  <div className="cell-sub">
                    {e.message}. Abnormal since {e.start_time}.
                  </div>
                </div>
              </div>
            ))
          )}
        </Card>
      </div>

      <div className="grid">
        <Card title={`Machines (${rows.length})`}>
          <div className="filters">
            {FILTERS.map((f) => (
              <button key={f} className={filter === f ? "chip on" : "chip"}
                      onClick={() => setFilter(f)}>{f}</button>
            ))}
          </div>
          <div className="table-wrap scroll">
            <table>
              <thead>
                <tr>
                  <th>Machine</th><th>Health</th><th>Failure risk</th>
                  <th>Life used</th><th>Main issue</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.asset_id}>
                    <td>{a.asset_name}<div className="cell-sub">{a.asset_type}</div></td>
                    <td>{a.health_score} <Badge kind={a.status}>{a.status}</Badge></td>
                    <td>{a.risk_pct != null ? `${a.risk_pct}%` : "-"}</td>
                    <td>{Math.round(a.life_used_pct)}%</td>
                    <td>{a.main_issue}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}