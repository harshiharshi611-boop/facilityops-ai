# Agentic FacilityOps AI Platform

AI-powered building operations and facility intelligence system. Multiple autonomous agents monitor facility data, detect problems, and recommend actions, with a React dashboard on top.

**Intern:** M. Harshitha (Infosys Springboard) | **Mentor:** Shwetha

> **Important:** All data in this project is **simulated** (seeded, so results are repeatable). No real facility or sensor data is used.

---

## Project status

| Milestone | Weeks | Scope | Status |
|---|---|---|---|
| M1 | 1-2 | Energy Intelligence and Monitoring | Done |
| M2 | 3-4 | Predictive Maintenance | Done (tag `milestone-2`) |
| M3 | 5-6 | Occupancy and Security | Planned |
| M4 | 7-8 | Cost Optimization, executive dashboards, orchestration, deployment | Planned |

---

## Tech stack

- **Backend:** Python, FastAPI
- **Agents:** LangGraph (Energy Agent, Maintenance Agent)
- **ML:** scikit-learn (Isolation Forest, Random Forest, Logistic Regression), pandas, joblib
- **Database:** PostgreSQL (`facilityops`)
- **Frontend:** React (Vite)
- **LLM (optional):** Anthropic Claude, used only to write the wording of recommendations. A rule-based fallback is used when the API is unavailable.

---

## Folder structure

```
facilityops/
├── backend/
│   ├── generate_data.py        # M1: simulated energy data
│   ├── load_data.py            # M1: load energy data into PostgreSQL
│   ├── analytics.py            # M1: energy analytics
│   ├── anomaly.py              # M1: anomaly detection
│   ├── agent.py                # M1: Energy Agent (LangGraph)
│   ├── generate_assets.py      # M2: assets, sensors, maintenance records
│   ├── load_assests.py         # M2: loader (filename kept as-is)
│   ├── health.py               # M2: health score 0-100
│   ├── behavior.py             # M2: abnormal behavior events
│   ├── predict.py              # M2: failure prediction model
│   ├── schedule.py             # M2: maintenance schedule
│   ├── maintenance_agent.py    # M2: Maintenance Agent (LangGraph, 9 nodes)
│   ├── maintenance_api.py      # M2: 11 maintenance endpoints
│   ├── verify_api.py           # M2: API check script
│   ├── main.py                 # FastAPI app (energy + maintenance)
│   └── .env                    # DATABASE_URL, ANTHROPIC_API_KEY (not committed)
├── frontend/                   # Vite React dashboard
└── data/
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

**Start the API**
```powershell
uvicorn main:app --reload
```
Open http://127.0.0.1:8000/docs to see all endpoints. In another terminal, `python verify_api.py` checks the maintenance endpoints.

**Start the dashboard**
```powershell
cd C:\facilityops\frontend
npm run dev
```
Use the **Energy / Maintenance** switch at the top of the dashboard.

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
6. **Dashboard:** Health, Schedule and Work Orders pages.

**Model comparison**

| Model | Precision | Recall | F1 |
|---|---|---|---|
| Random Forest | 93.6% | 86.3% | 89.8% |
| Logistic Regression | 79.7% | 92.2% | 85.5% |
| Simple rule | 97.7% | 82.4% | 89.4% |

---

## Limitations (stated openly)

- All data is **simulated**. Real sensors would be noisier.
- The test set is small (**6 breakdowns**), so metrics can change with more data.
- A **simple rule is almost as good** as the Random Forest (F1 89.4% vs 89.8%).
- Savings figures (Rs 382,100 and 221 h) are **estimates**, not measured results.
- Alerts are **recorded but not sent**. Email, SMS and Slack come in Milestone 4.
- Work orders are **read-only** in the dashboard.
- The Claude API wording path is used only when credits are available; otherwise the rule-based fallback writes the text.

---

## Roadmap

- **M3 (weeks 5-6):** Occupancy Agent and Security Agent (`occupancy_records`, `security_events`); target occupancy forecasting accuracy of 80% or more.
- **M4 (weeks 7-8):** Cost Optimization Agent, executive dashboards, cross-agent orchestration, alert module (email, SMS, Slack, escalations, tickets), cloud deployment.