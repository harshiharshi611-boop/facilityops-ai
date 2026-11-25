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

const OCCUPANCY_TABS = [
  { to: "/occupancy", label: "Space Utilization", end: true },
  { to: "/occupancy/forecast", label: "Forecast" },
  { to: "/occupancy/alerts", label: "Incidents & Alerts" },
];

const SECURITY_TABS = [
  { to: "/security", label: "Security Overview", end: true },
  { to: "/security/alerts", label: "Alerts & Investigation" },
  { to: "/security/visitors", label: "Visitors & Accuracy" },
];

// One entry per module (the pill at the top) with its three tabs.
const SECTIONS = {
  energy: { label: "Energy", to: "/", tabs: ENERGY_TABS,
    title: "Energy Intelligence Dashboard", milestone: "Milestone 1" },
  maintenance: { label: "Maintenance", to: "/maintenance", tabs: MAINTENANCE_TABS,
    title: "Predictive Maintenance Dashboard", milestone: "Milestone 2" },
  occupancy: { label: "Occupancy", to: "/occupancy", tabs: OCCUPANCY_TABS,
    title: "Occupancy Intelligence Dashboard", milestone: "Milestone 3" },
  security: { label: "Security", to: "/security", tabs: SECURITY_TABS,
    title: "Security Intelligence Dashboard", milestone: "Milestone 3" },
};

function sectionFor(pathname) {
  if (pathname.startsWith("/maintenance")) return "maintenance";
  if (pathname.startsWith("/occupancy")) return "occupancy";
  if (pathname.startsWith("/security")) return "security";
  return "energy";
}

export default function App() {
  const [facilities, setFacilities] = useState([]);
  const [facilityId, setFacilityId] = useState(1);
  const { pathname } = useLocation();
  const current = sectionFor(pathname);
  const section = SECTIONS[current];

  useEffect(() => {
    api.getFacilities().then(setFacilities).catch(() => {});
  }, []);

  return (
    <div className="app">
      <div className="module">
        {Object.entries(SECTIONS).map(([key, s]) => (
          <Link key={key} to={s.to} className={"pill" + (key === current ? " active" : "")}>
            {s.label}
          </Link>
        ))}
      </div>

      <div className="header">
        <div>
          <h1>{section.title}</h1>
          <p>Agentic FacilityOps AI Platform | {section.milestone}</p>
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
        {section.tabs.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end}>{t.label}</NavLink>
        ))}
      </nav>

      <Outlet context={{ facilityId }} />
    </div>
  );
}