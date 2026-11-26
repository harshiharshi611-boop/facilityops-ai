# Agentic FacilityOps AI Platform

AI-powered building operations and facility intelligence system. Multiple autonomous agents monitor facility data, detect problems, and recommend actions, with a React dashboard on top.

**Intern:** M. Harshitha (Infosys Springboard) | **Mentor:** Shwetha

> **Important:** All data in this project is **simulated** (seeded, so results are repeatable). No real facility, sensor, badge or visitor data is used.

---

## Project status

| Milestone | Weeks | Scope | Status |
|---|---|---|---|
| M1 | 1-2 | Energy Intelligence and Monitoring | Done |
| M2 | 3-4 | Predictive Maintenance | Done (tag `milestone-2`) |
| M3 | 5-6 | Occupancy and Security Intelligence | Done (tag `milestone-3`) |
| M4 | 7-8 | Cost Optimization, executive dashboards, orchestration, deployment | Planned |

---

## Tech stack

- **Backend:** Python, FastAPI
- **Agents:** LangGraph (Energy, Maintenance, Occupancy and Security agents)
- **ML:** scikit-learn (Isolation Forest, Random Forest, Gradient Boosting, Logistic Regression), pandas, joblib
- **Database:** PostgreSQL (`facilityops`)
- **Frontend:** React (Vite), React Router
- **LLM (optional):** Anthropic Claude, used only to write the wording of recommendations and alerts. A rule-based fallback is used when the API is unavailable.

---

## Folder structure

```
facilityops/
├── backend/
│   ├── generate_data.py                  # M1: simulated energy data
│   ├── load_data.py                      # M1: load energy data into PostgreSQL
│   ├── analytics.py                      # M1: energy analytics
│   ├── anomaly.py                        # M1: anomaly detection
│   ├── agent.py                          # M1: Energy Agent (LangGraph)
│   ├── generate_assets.py                # M2: assets, sensors, maintenance records
│   ├── load_assests.py                   # M2: loader (filename kept as-is)
│   ├── health.py                         # M2: health score 0-100
│   ├── behavior.py                       # M2: abnormal behavior events
│   ├── predict.py                        # M2: failure prediction model
│   ├── schedule.py                       # M2: maintenance schedule
│   ├── maintenance_agent.py              # M2: Maintenance Agent (LangGraph, 9 nodes)
│   ├── maintenance_api.py                # M2: 11 maintenance endpoints
│   ├── verify_api.py                     # M2: API check script
│   ├── generate_occupancy_security.py    # M3: simulated occupancy, badge, CCTV, visitor data
│   ├── load_occupancy_security.py        # M3: load the M3 data into PostgreSQL
│   ├── occupancy.py                      # M3: utilization, overcrowding detection, heatmap
│   ├── occupancy_forecast.py             # M3: 7-day occupancy forecast
│   ├── security.py                       # M3: 9 security rules + Isolation Forest comparison
│   ├── agent_common.py                   # M3: shared agent helpers (wording, saving, run log)
│   ├── occupancy_agent.py                # M3: Occupancy Agent (LangGraph)
│   ├── security_agent.py                 # M3: Security Agent (LangGraph)
│   ├── api_utils.py                      # M3: shared API helpers
│   ├── occupancy_api.py                  # M3: 9 occupancy endpoints
│   ├── security_api.py                   # M3: 9 security endpoints
│   ├── verify_api_m3.py                  # M3: API check script (35 checks)
│   ├── main.py                           # FastAPI app (energy + maintenance + occupancy + security)
│   ├── models/                           # saved ML models (.joblib)
│   └── .env                              # DATABASE_URL, ANTHROPIC_API_KEY (not committed)
├── frontend/
│   └── src/
│       ├── App.jsx, main.jsx             # 4 modules, each with 3 tabs
│       ├── pages/                        # Energy pages (M1)
│       ├── pages/maintenance/            # 3 maintenance pages (M2)
│       ├── pages/occupancy/              # 3 occupancy pages (M3)
│       ├── pages/security/               # 3 security pages (M3)
│       └── m3/                           # shared M3 code (API calls, components, styles)
└── data/                                 # generated CSV files (data/m3 for Milestone 3)
```

---

## Setup (Windows, PowerShell)

**1. Database**
Create a local PostgreSQL database named `facilityops`.

**2. Backend**
```powershell
cd C:\facilityops\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `backend\.env`:
```
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/facilityops
ANTHROPIC_API_KEY=your_key_here
```

**3. Frontend**
```powershell
cd C:\facilityops\frontend
npm install
```

---

## Run order

Run from `backend\` with the virtual environment active.

**Milestone 1 (Energy)**
```powershell
python generate_data.py
python load_data.py
python agent.py
```

**Milestone 2 (Maintenance)**
```powershell
python generate_assets.py
python load_assests.py
python health.py
python behavior.py
python predict.py
python schedule.py
python maintenance_agent.py --dry-run   # preview, writes nothing
python maintenance_agent.py             # real run: work orders + alerts
```

**Milestone 3 (Occupancy and Security)**
```powershell
python generate_occupancy_security.py
python load_occupancy_security.py
python occupancy.py
python occupancy_forecast.py
python security.py
python occupancy_agent.py --dry-run     # preview, saves nothing
python security_agent.py --dry-run
python occupancy_agent.py               # real run: saves alerts (no duplicates on re-run)
python security_agent.py
```

**Start the API**
```powershell
uvicorn main:app --reload
```
Open http://127.0.0.1:8000/docs to see all endpoints. In another terminal:
```powershell
python verify_api.py        # maintenance endpoints
python verify_api_m3.py     # occupancy and security endpoints (35 checks)
```

**Start the dashboard**
```powershell
cd C:\facilityops\frontend
npm run dev
```
Use the four buttons at the top (**Energy, Maintenance, Occupancy, Security**). Each has three tabs, and the facility dropdown applies to all of them.

---

## Milestone 1: Energy Intelligence

- 4,320 hourly records across 2 facilities
- Energy Agent (LangGraph): load, validate, detect, analyze, recommend, save
- Anomaly detection: accuracy **99.9%** (target 85% or more), precision / recall / F1 **99.1%**, Isolation Forest **99.4%**
- Dashboard: Overview, Analytics and Anomalies, AI Agent pages with a facility dropdown

## Milestone 2: Predictive Maintenance

**Data (simulated):** 48 machines (24 per facility, 8 equipment types), 103,098 hourly sensor readings over 90 days, 216 maintenance records.

**What was built**

1. **Health score (0-100):** sensors 55%, age 15%, overdue maintenance 15%, recent failures 15%. Bands: Excellent 85+, Good 70-84, Warning 50-69, Critical below 50.
2. **Abnormal behavior detection:** 20 events found (10 breakdowns, 6 temporary spikes, 4 ongoing). Warned before 10 of 10 breakdowns, about 11.6 days ahead on average, with 0 false alarms.
3. **Failure prediction:** Random Forest, precision 93.6%, recall 86.3%, F1 89.8%, ROC-AUC 0.946. Warned before 6 of 6 test breakdowns, about 7.5 days ahead on average.
4. **Maintenance schedule:** 29 jobs (4 Emergency, 8 Planned, 17 Routine), capped at 2 planned jobs per facility per day.
5. **Maintenance Agent (LangGraph, 9 nodes):** stops early on bad data, creates work orders and alerts. The LLM only writes the wording.
6. **Dashboard:** Equipment Health, Predictions and Schedule, Work Orders and Alerts.

**Model comparison**

| Model | Precision | Recall | F1 |
|---|---|---|---|
| Random Forest | 93.6% | 86.3% | 89.8% |
| Logistic Regression | 79.7% | 92.2% | 85.5% |
| Simple rule | 97.7% | 82.4% | 89.4% |

## Milestone 3: Occupancy and Security Intelligence

**Data (simulated):** 16 zones (8 per facility, including a restricted Server Room and ICU), 34,560 hourly occupancy records over 90 days, 65,549 badge swipes, 4,426 CCTV events and 1,582 visitors. I planted a known **answer key** (20 overcrowding events and 74 security incidents) so detection can be graded honestly. The answer keys are used only for grading.

### Occupancy

- **Utilization:** occupancy rate (weekdays 08:00-19:00) is 49.9% at Tech Park Block A and 57.4% at City Hospital, with a peak hour of 11:00 at both. The Training Hall is flagged as underused (23.9% full in busy hours).
- **Overcrowding detection:** a zone is flagged when it holds more people than its capacity. It found 31 incidents (16 and 15) and **all 20 of the 20 planted events**. Precision is 61.3% because 12 flagged peaks were natural, not planted. A near-full warning at 90% flags 135 hours (precision 14.1%), which is too noisy to use as an alarm.
- **Heatmap:** average % of capacity for each zone and hour, weekday and weekend.
- **Forecast (target: accuracy of 80% or more):** accuracy is defined as 100% minus the total error. It is tested on 27 days the model never saw, 7 days ahead, week by week.

| Model | Accuracy | Avg error (people) | Within 10% of capacity |
|---|---|---|---|
| Gradient Boosting (ML) | **84.5%** | 3.77 | 82.0% |
| Hour-of-week average | 85.0% | 3.66 | 83.2% |
| Same hour last week | 80.0% | 4.88 | 78.9% |

  10 of 16 zones reach 80%. The forecast covers 30 Oct to 5 Nov 2026 (2,688 rows).
- **Occupancy Agent (LangGraph):** load, check, analyze, pick recent window, check forecast, build alerts, reword, save. Stops early on bad data.

### Security

- **9 detection rules:** repeated denied swipes, restricted room opened while the badge was outside the building, same badge at two facilities within 30 minutes, forced door, tailgating, night loitering, visitor overstay, visitor with no check-out, visitor in a restricted room.
- **Result:** 75 alerts (30 Critical, 21 High, 18 Medium, 6 Low). The rules found **74 of 74** planted incidents with 1 false alarm (precision 98.7%, F1 99.3%).
- **ML comparison:** an Isolation Forest flagged 47 of 16,450 badge-days. It found only 2 of 10 repeated-denied incidents, 7 of 8 off-hours cases and 0 of 4 impossible-travel cases, so the rules are the main detector.
- **Security Agent (LangGraph):** load, check, detect, pick recent window, **investigate** (collects evidence for each alert), build alerts, reword, save. Each alert has a recommended action and an escalation target.
- **Alerts:** stored in `occupancy_alerts` and `security_alerts`, with every run logged in `m3_agent_runs`. Re-running does not create duplicates. `--dry-run` previews without saving. Claude only writes wording, and rule-based text is used when it is not available.

### API and dashboard

- **18 read-only endpoints** (9 occupancy, 9 security), checked by `verify_api_m3.py` (35 checks).
- **Occupancy dashboard tabs:** Space Utilization, Forecast, Incidents and Alerts.
- **Security dashboard tabs:** Security Overview, Alerts and Investigation (with an Investigate view showing the badge timeline, door swipes and CCTV around an event), Visitors and Accuracy.

---

## Limitations (stated openly)

- All data is **simulated**, including the planted incidents. Real data will be messier.
- Test sets are small (6 breakdowns in M2, 20 overcrowding events and 74 security incidents in M3), so metrics can change with more data.
- **Simple methods are almost as good as ML:** the simple rule in M2 and the hour-of-week average in M3 match or beat the ML models on this simulated data.
- **The security score is optimistic:** the simulated incidents are clean, and three rules were fixed after the first test run. One false alarm remains, caused by the simulator logging two swipes in the same second.
- **The occupancy forecast cannot predict sudden overcrowding.** In the test period it warned about none of the 10 real over-capacity hours. It is for planning space and staff. Overcrowding alarms come from the detection step.
- **Small zones such as the Server Room and ICU do not reach 80% forecast accuracy,** because a few people of random change is a large percentage.
- Savings figures in M2 (Rs 382,100 and 221 h) are **estimates**, not measured results.
- Alerts are **recorded but not sent.** Email, SMS and Slack come in Milestone 4.
- Maintenance work orders and the M3 alerts are **read-only** in the dashboard.
- M3 alerts use their own tables and are not yet combined with the M2 `alerts` table (planned for M4).
- Agent alerts cover the **last 14 days of the simulated data** (up to 29 Oct 2026), not today's date.
- The Claude wording path is used only when credits are available; otherwise the rule-based fallback writes the text.

---

## Roadmap

- **M4 (weeks 7-8):** Cost Optimization Agent, executive dashboards, cross-agent orchestration (including combining all agents' alerts), an alert module (email, SMS, Slack, escalations, tickets), and deployment on Azure, OCI or AWS.