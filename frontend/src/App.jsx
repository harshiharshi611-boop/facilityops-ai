import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import * as api from "./api";
import "./App.css";

export default function App() {
  const [facilities, setFacilities] = useState([]);
  const [facilityId, setFacilityId] = useState(1);

  useEffect(() => {
    api.getFacilities().then(setFacilities).catch(() => {});
  }, []);

  return (
    <div className="app">
      <div className="header">
        <div>
          <h1>Energy Intelligence Dashboard</h1>
          <p>Agentic FacilityOps AI Platform | Milestone 1</p>
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
        <NavLink to="/" end>Overview</NavLink>
        <NavLink to="/analytics">Analytics &amp; Anomalies</NavLink>
        <NavLink to="/agent">AI Agent</NavLink>
      </nav>

      <Outlet context={{ facilityId }} />
    </div>
  );
}