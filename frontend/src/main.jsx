import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App";
import Overview from "./pages/Overview";
import Analytics from "./pages/Analytics";
import AgentPage from "./pages/AgentPage";
import HealthPage from "./pages/maintenance/HealthPage";
import SchedulePage from "./pages/maintenance/SchedulePage";
import WorkOrdersPage from "./pages/maintenance/WorkOrdersPage";
import UtilizationPage from "./pages/occupancy/UtilizationPage";
import ForecastPage from "./pages/occupancy/ForecastPage";
import IncidentsPage from "./pages/occupancy/IncidentsPage";
import SecurityOverviewPage from "./pages/Security/SecurityOverviewPage";
import AlertsPage from "./pages/Security/AlertsPage";
import VisitorsPage from "./pages/Security/VisitorsPage";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Overview />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="agent" element={<AgentPage />} />
          <Route path="maintenance" element={<HealthPage />} />
          <Route path="maintenance/schedule" element={<SchedulePage />} />
          <Route path="maintenance/work-orders" element={<WorkOrdersPage />} />
          <Route path="occupancy" element={<UtilizationPage />} />
          <Route path="occupancy/forecast" element={<ForecastPage />} />
          <Route path="occupancy/alerts" element={<IncidentsPage />} />
          <Route path="security" element={<SecurityOverviewPage />} />
          <Route path="security/alerts" element={<AlertsPage />} />
          <Route path="security/visitors" element={<VisitorsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>
);