"""
load_occupancy_security.py  (Milestone 3 - Step 1)
Reads the CSV files from ../data/m3/ and saves them into PostgreSQL.
"""
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parent / ".env")
DATA = Path(__file__).resolve().parent.parent / "data" / "m3"

DATE_COLS = {
    "occupancy_records": ["timestamp"],
    "occupancy_scenarios": ["start_time"],
    "access_logs": ["timestamp"],
    "cctv_events": ["timestamp"],
    "visitors": ["check_in", "check_out"],
    "security_scenarios": ["start_time"],
}
TABLES = ["occupancy_zones", "occupancy_records", "occupancy_scenarios",
          "access_logs", "cctv_events", "visitors", "security_scenarios"]


def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not found. Check backend/.env")
    engine = create_engine(url)
    for name in TABLES:
        f = DATA / f"{name}.csv"
        if not f.exists():
            raise SystemExit(f"Missing {f}. Run generate_occupancy_security.py first.")
        df = pd.read_csv(f)
        for c in DATE_COLS.get(name, []):
            df[c] = pd.to_datetime(df[c])          # needed, otherwise dates load as text
        df.to_sql(name, engine, if_exists="replace", index=False, chunksize=5000)
        print(f"loaded {name:22s} {len(df):>8,} rows")

    with engine.connect() as conn:
        print("\nCheck from the database:")
        for name in TABLES:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
            print(f"  {name:22s} {n:>8,}")


if __name__ == "__main__":
    main()