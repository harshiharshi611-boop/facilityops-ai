import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import * as api from "./api";
import "./App.css";

const ENERGY_TABS = [
  { to: "/", label: "Overview", end: true },
  { to: "/analytics", label: "Analytics & Anomalies" },
  { to: "/agent", label: "AI Agent" },
];

const MAINTENANCE_TABS = [
  { to: "/maintenance", label: "Equipment Health", end: true },
  { to: "/maintenance/schedule", label: "Predictions & Schedule" },
  { to: "/maintenance/work-orders", label: "Work Orders & Alerts" },
];

export default function App() {
  const [facilities, setFacilities] = useState([]);
  const [facilityId, setFacilityId] = useState(1);
  const { pathname } = useLocation();
  const maintenance = pathname.startsWith("/maintenance");
  const tabs = maintenance ? MAINTENANCE_TABS : ENERGY_TABS;

  useEffect(() => {
    api.getFacilities().then(setFacilities).catch(() => {});
  }, []);

  return (
    <div className="app">
      <div className="module">
        <Link to="/" className={"pill" + (!maintenance ? " active" : "")}>Energy</Link>
        <Link to="/maintenance" className={"pill" + (maintenance ? " active" : "")}>Maintenance</Link>
      </div>

      <div className="header">
        <div>
          <h1>{maintenance ? "Predictive Maintenance Dashboard" : "Energy Intelligence Dashboard"}</h1>
          <p>Agentic FacilityOps AI Platform | {maintenance ? "Milestone 2" : "Milestone 1"}</p>
        </div>
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
      </div>

      <nav className="tabs">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end}>{t.label}</NavLink>
        ))}
      </nav>

      <Outlet context={{ facilityId }} />
    </div>
  );
}