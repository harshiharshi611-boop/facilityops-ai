"""
api_utils.py  (Milestone 3 - Step 6)
Small helpers used by occupancy_api.py and security_api.py.
"""
from functools import lru_cache

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import inspect, text

from agent_common import get_engine as _make_engine

FACILITIES = {1: "Tech Park Block A", 2: "City Hospital"}
SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


@lru_cache(maxsize=1)
def engine():
    return _make_engine()


def table_exists(name):
    return inspect(engine()).has_table(name)


def need_tables(*names):
    missing = [n for n in names if not table_exists(n)]
    if missing:
        raise HTTPException(503, f"Missing table(s): {', '.join(missing)}. Run the earlier Milestone 3 steps first.")


def check_facility(facility_id):
    if facility_id not in FACILITIES:
        raise HTTPException(404, f"Unknown facility_id {facility_id}. Use one of {list(FACILITIES)}")


def q(sql, **params):
    return pd.read_sql(text(sql), engine(), params=params)


def clean(df, time_cols=()):
    """DataFrame -> list of plain dicts that are safe to send as JSON."""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]) or c in time_cols:
            t = pd.to_datetime(df[c], errors="coerce")
            df[c] = t.dt.strftime("%Y-%m-%d %H:%M").where(t.notna(), None)
    df = df.astype(object).where(df.notna(), None)
    return df.to_dict(orient="records")


def sort_by_severity(df, time_col):
    if df.empty:
        return df
    d = df.copy()
    d["_r"] = d["severity"].map(SEVERITY_RANK).fillna(9)
    d["_t"] = pd.to_datetime(d[time_col], errors="coerce")
    return d.sort_values(["_r", "_t"], ascending=[True, False]).drop(columns=["_r", "_t"])