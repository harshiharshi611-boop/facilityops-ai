import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

ddl = """
DROP TABLE IF EXISTS work_orders CASCADE;
DROP TABLE IF EXISTS sensor_readings CASCADE;
DROP TABLE IF EXISTS maintenance_records CASCADE;
DROP TABLE IF EXISTS asset_scenarios CASCADE;
DROP TABLE IF EXISTS assets CASCADE;

CREATE TABLE assets (
    asset_id              INT PRIMARY KEY,
    facility_id           INT REFERENCES facilities(facility_id),
    asset_name            VARCHAR(100),
    asset_type            VARCHAR(50),
    status                VARCHAR(30),
    install_date          DATE,
    expected_life_years   INT,
    criticality           INT,
    last_service_date     DATE,
    service_interval_days INT
);

CREATE TABLE maintenance_records (
    maintenance_id   INT PRIMARY KEY,
    asset_id         INT REFERENCES assets(asset_id),
    issue_type       VARCHAR(100),
    maintenance_type VARCHAR(20),
    maintenance_date DATE,
    status           VARCHAR(20),
    cost_rs          NUMERIC,
    downtime_hours   NUMERIC
);

CREATE TABLE sensor_readings (
    reading_id     SERIAL PRIMARY KEY,
    asset_id       INT REFERENCES assets(asset_id),
    timestamp      TIMESTAMP,
    temperature_c  NUMERIC,
    vibration_mm_s NUMERIC,
    current_amp    NUMERIC
);
CREATE INDEX idx_sensor_asset_time ON sensor_readings(asset_id, timestamp);

CREATE TABLE asset_scenarios (
    asset_id     INT PRIMARY KEY REFERENCES assets(asset_id),
    scenario     VARCHAR(20),
    failure_time TIMESTAMP,
    ramp_days    INT
);

CREATE TABLE work_orders (
    work_id     SERIAL PRIMARY KEY,
    asset_id    INT REFERENCES assets(asset_id),
    created_at  TIMESTAMP DEFAULT NOW(),
    priority    VARCHAR(10),
    title       VARCHAR(200),
    description TEXT,
    due_date    DATE,
    status      VARCHAR(20) DEFAULT 'open',
    source      VARCHAR(60)
);
"""

with engine.begin() as conn:
    conn.execute(text(ddl))

def load(name, file, dates=(), **kw):
    df = pd.read_csv(f"../data/{file}")
    for col in dates:
        df[col] = pd.to_datetime(df[col])
    if name == "asset_scenarios":
        df["ramp_days"] = df["ramp_days"].astype("Int64")
    df.to_sql(name, engine, if_exists="append", index=False, **kw)
    print("loaded", name, len(df), "rows")

load("assets", "assets.csv",
     dates=["install_date", "last_service_date"])
load("asset_scenarios", "asset_scenarios.csv",
     dates=["failure_time"])
load("maintenance_records", "maintenance_records.csv",
     dates=["maintenance_date"])
load("sensor_readings", "sensor_readings.csv",
     dates=["timestamp"], chunksize=5000, method="multi")
print("Maintenance data loaded into PostgreSQL")