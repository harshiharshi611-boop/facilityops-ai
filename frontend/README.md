# Agentic FacilityOps AI Platform: Milestone 1 (Energy Intelligence)

An AI Energy Agent that monitors building electricity and water usage,
detects anomalies, and recommends savings.

## Features
- Energy analytics: total usage, cost, carbon, efficiency score, trends
- Anomaly detection (Robust Z-score + Isolation Forest) with measured accuracy
- LangGraph Energy Agent: load, validate, detect, analyze, recommend, save
- LLM recommendations grounded in computed data, with a rule-based fallback
- FastAPI backend with 7 endpoints
- React dashboard (Recharts)

## Tech stack
Python, FastAPI, LangGraph, scikit-learn, pandas, PostgreSQL, React, Recharts, Anthropic Claude API

## Architecture
Data (CSV) -> PostgreSQL -> Analytics + Anomaly Detection -> LangGraph Agent
-> FastAPI -> React Dashboard

## Results
- Anomaly detection accuracy: 99.9% (target: 85% or more)
- Precision: 99.1% | Recall: 99.1% | F1: 99.1%

## Setup
1. Install Python 3.11+, Node.js, PostgreSQL
2. `cd backend && python -m venv venv && venv\Scripts\activate`
3. `pip install -r requirements.txt`
4. Create `backend/.env` with DATABASE_URL and ANTHROPIC_API_KEY
5. `python generate_data.py && python load_data.py`
6. `uvicorn main:app --reload`
7. In another terminal: `cd frontend && npm install && npm run dev`
8. Open http://localhost:5173

## Assumptions
- Synthetic data with labeled anomalies (so accuracy can be measured)
- Tariff Rs 8 per kWh, carbon factor 0.82 kg per kWh
- HVAC setback saving assumed at 20% of off-hours HVAC

## Limitations and next steps
- Real building data will be noisier, so accuracy will be lower
- Milestone 2: Maintenance Agent; later milestones add the other agents

## Screenshots
(add images from docs/screenshots/)