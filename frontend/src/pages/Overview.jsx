import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import {
  LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import * as api from "../api";
import { Kpi, Card, inr } from "../components";

const COLORS = ["#2563eb", "#10b981", "#8b5cf6", "#94a3b8"];

export default function Overview() {
  const { facilityId } = useOutletContext();
  const [summary, setSummary] = useState(null);
  const [trends, setTrends] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    setSummary(null);
    setTrends(null);
    Promise.all([api.getSummary(facilityId), api.getTrends(facilityId)])
      .then(([s, t]) => { setSummary(s); setTrends(t); })
      .catch(() => setError("Cannot reach the API. Is uvicorn running on port 8000?"));
  }, [facilityId]);

  if (error) return <div className="error">{error}</div>;
  if (!summary || !trends) return <p>Loading...</p>;

  const k = summary.kpis;
  const daily = trends.daily.map((d) => ({
    date: String(d.timestamp).slice(5, 10),
    kwh: d.electricity_usage,
  }));

  return (
    <>
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
    </>
  );
}