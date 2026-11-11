import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import * as api from "./api";
import "./App.css";

const COLORS = ["#2563eb", "#10b981", "#8b5cf6", "#94a3b8"];
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN");

function Kpi({ label, value, sub }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      <div className="sub">{sub}</div>
    </div>
  );
}

function Card({ title, children }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export default function App() {
  const [facilities, setFacilities] = useState([]);
  const [facilityId, setFacilityId] = useState(1);
  const [summary, setSummary] = useState(null);
  const [trends, setTrends] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [recs, setRecs] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [agentRun, setAgentRun] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getFacilities().then(setFacilities).catch(() => {});
    api.getMetrics().then(setMetrics).catch(() => {});
  }, []);

  useEffect(() => {
    setError("");
    setAgentRun(null);
    Promise.all([
      api.getSummary(facilityId),
      api.getTrends(facilityId),
      api.getAnomalies(facilityId),
      api.getRecs(facilityId),
    ])
      .then(([s, t, a, r]) => {
        setSummary(s);
        setTrends(t);
        setAnomalies(a);
        setRecs(r);
      })
      .catch(() =>
        setError("Cannot reach the API. Is uvicorn running on port 8000?")
      );
  }, [facilityId]);

  const runAgent = async () => {
    setRunning(true);
    setError("");
    try {
      setAgentRun(await api.runAgent(facilityId));
      setRecs(await api.getRecs(facilityId));
    } catch {
      setError("Agent run failed. Check the uvicorn terminal for the error.");
    } finally {
      setRunning(false);
    }
  };

  if (!summary || !trends) {
    return (
      <div className="app">
        {error ? <div className="error">{error}</div> : <p>Loading dashboard...</p>}
      </div>
    );
  }

  const k = summary.kpis;
  const daily = trends.daily.map((d) => ({
    date: String(d.timestamp).slice(5, 10),
    kwh: d.electricity_usage,
  }));
  const hourly = trends.hourly.map((h) => ({
    hour: `${h.hour}:00`,
    kwh: h.electricity_usage,
  }));
  const wd = trends.weekday_vs_weekend;

  return (
    <div className="app">
      <div className="header">
        <div>
          <h1>Energy Intelligence Dashboard</h1>
          <p>Agentic FacilityOps AI Platform | Milestone 1</p>
        </div>
        <div className="controls">
          <select
            value={facilityId}
            onChange={(e) => setFacilityId(Number(e.target.value))}
          >
            {facilities.map((f) => (
              <option key={f.facility_id} value={f.facility_id}>
                {f.facility_name}
              </option>
            ))}
          </select>
          <button className="primary" onClick={runAgent} disabled={running}>
            {running ? "Agent running..." : "Run Energy Agent"}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="grid kpis">
        <Kpi label="Total energy" value={`${k.total_mwh} MWh`} sub="last 90 days" />
        <Kpi label="Electricity cost" value={inr(k.electricity_cost)} sub="at ₹8 per kWh" />
        <Kpi label="Carbon emitted" value={`${Math.round(k.carbon_kg / 1000)} t CO₂`} sub="0.82 kg per kWh" />
        <Kpi label="Efficiency score" value={`${k.efficiency_score}/100`} sub="off-hours vs working hours" />
        <Kpi label="Water used" value={`${Math.round(k.water_litres / 1000)} kL`} sub={inr(k.water_cost)} />
        <Kpi label="Peak demand" value={`${k.peak_demand_kw} kW`} sub="highest single hour" />
      </div>

      <div className="grid two">
        <Card title="Daily energy consumption (kWh)">
          <div className="chart">
            <ResponsiveContainer>
              <LineChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={30} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Line type="monotone" dataKey="kwh" stroke="#2563eb" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Energy distribution">
          <div className="chart">
            <ResponsiveContainer>
              <PieChart>
                <Pie
                  data={summary.distribution}
                  dataKey="kwh"
                  nameKey="name"
                  innerRadius={55}
                  outerRadius={90}
                  label={(e) => `${e.name} ${e.percent}%`}
                >
                  {summary.distribution.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid two">
        <Card title="Average usage by hour of day (kWh)">
          <div className="chart">
            <ResponsiveContainer>
              <BarChart data={hourly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="hour" tick={{ fontSize: 11 }} interval={2} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="kwh" fill="#10b981" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="muted">
            Weekday average {wd.Weekday} kWh vs weekend {wd.Weekend} kWh per hour.
          </p>
        </Card>

        <Card title="Anomaly detection accuracy">
          {!metrics ? (
            <p className="muted">Loading model metrics...</p>
          ) : (
            <>
              <p>
                Target: {metrics.target_accuracy}% or more{" "}
                <span className={`badge ${metrics.zscore.accuracy >= metrics.target_accuracy ? "pass" : "high"}`}>
                  {metrics.zscore.accuracy >= metrics.target_accuracy ? "target met" : "below target"}
                </span>
              </p>
              <div className="metrics">
                {["accuracy", "precision", "recall", "f1"].map((m) => (
                  <div className="metric" key={m}>
                    <div className="label">{m}</div>
                    <div className="value">{metrics.zscore[m]}%</div>
                  </div>
                ))}
              </div>
              <p className="muted">
                Robust Z-score on {metrics.rows_evaluated} hourly readings
                ({metrics.labeled_anomalies} labeled anomalies). Isolation Forest
                accuracy: {metrics.isolation_forest.accuracy}%.
              </p>
            </>
          )}
        </Card>
      </div>

      <div className="grid">
        <Card title={`Detected anomalies (${anomalies.total} found, worst 10 shown)`}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Issue</th>
                  <th>Severity</th>
                  <th>Extra kWh</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {anomalies.items.map((a, i) => (
                  <tr key={i}>
                    <td>{String(a.timestamp).slice(0, 16)}</td>
                    <td>{a.issue}</td>
                    <td><span className={`badge ${a.severity}`}>{a.severity}</span></td>
                    <td>{a.excess_kwh}</td>
                    <td>{a.max_z}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid">
        <Card title="AI recommendations">
          {agentRun && (
            <>
              <p className="muted">Agent finished. Source: {agentRun.source}</p>
              <ol className="steps">
                {agentRun.steps.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
            </>
          )}
          {recs.items.length === 0 ? (
            <p className="muted">{recs.message || "No recommendations yet."} Click "Run Energy Agent".</p>
          ) : (
            recs.items.map((r, i) => (
              <div className="rec" key={i}>
                <div className="rec-title">
                  <span className={`badge ${r.priority}`}>{r.priority}</span>
                  {r.title}
                </div>
                <p>{r.detail}</p>
                {Number(r.est_saving_rs) > 0 && (
                  <div className="saving">
                    Estimated saving: {inr(Math.round(r.est_saving_rs))} per month
                  </div>
                )}
              </div>
            ))
          )}
        </Card>
      </div>
    </div>
  );
}