import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

ddl = """
DROP TABLE IF EXISTS energy_usage CASCADE;
DROP TABLE IF EXISTS facilities CASCADE;

CREATE TABLE facilities (
    facility_id   INT PRIMARY KEY,
    facility_name VARCHAR(100),
    facility_type VARCHAR(50),
    location      VARCHAR(100)
);

CREATE TABLE energy_usage (
    energy_id         SERIAL PRIMARY KEY,
    facility_id       INT REFERENCES facilities(facility_id),
    timestamp         TIMESTAMP,
    electricity_usage NUMERIC,
    water_usage       NUMERIC,
    hvac_kwh          NUMERIC,
    lighting_kwh      NUMERIC,
    equipment_kwh     NUMERIC,
    other_kwh         NUMERIC,
    is_anomaly        INT,
    anomaly_type      VARCHAR(30)
);

CREATE INDEX idx_energy_time ON energy_usage(facility_id, timestamp);
"""

with engine.begin() as conn:
    conn.execute(text(ddl))

pd.read_csv("../data/facilities.csv").to_sql(
    "facilities", engine, if_exists="append", index=False)
energy = pd.read_csv("../data/energy_usage.csv", parse_dates=["timestamp"])
energy.to_sql("energy_usage", engine, if_exists="append", index=False)

print("Data loaded into PostgreSQL")