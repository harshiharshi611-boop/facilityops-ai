// M3Page.jsx - wrapper used by every Occupancy and Security page (styles + "simulated data" banner)
import React from "react";
import "./m3.css";

export default function M3Page({ children }) {
  return (
    <div className="m3-root">
      <div className="m3-banner">Simulated data. Alerts are recorded here, not yet sent.</div>
      <div className="m3-page">{children}</div>
    </div>
  );
}