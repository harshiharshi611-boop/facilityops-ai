import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import * as api from "../api";
import { Card } from "../components";

export default function Analytics() {
  const { facilityId } = useOutletContext();
  const [trends, setTrends] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getMetrics().then(setMetrics).catch(() => {});
  }, []);

  useEffect(() => {
    setError("");
    setTrends(null);
    setAnomalies(null);
    Promise.all([api.getTrends(facilityId), api.getAnomalies(facilityId)])
      .then(([t, a]) => { setTrends(t); setAnomalies(a); })
      .catch(() => setError("Cannot reach the API. Is uvicorn running on port 8000?"));
  }, [facilityId]);

  if (error) return <div className="error">{error}</div>;
  if (!trends || !anomalies) return <p>Loading...</p>;

  const hourly = trends.hourly.map((h) => ({
    hour: `${h.hour}:00`,
    kwh: h.electricity_usage,
  }));
  const wd = trends.weekday_vs_weekend;

  return (
    <>
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
                Robust Z-score on {metrics.rows_evaluated} hourly readings (
                {metrics.labeled_anomalies} labeled anomalies). Isolation Forest
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
                  <th>Time</th><th>Issue</th><th>Severity</th>
                  <th>Extra kWh</th><th>Score</th>
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
    </>
  );
}