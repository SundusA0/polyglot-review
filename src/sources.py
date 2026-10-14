"""Data sources for the usage dashboard: demo CSVs, uploaded CSVs, a local DuckDB
run of the warehouse SQL, or a live Databricks SQL warehouse query.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from .config import DATABRICKS_CSV, FEATURE_USAGE_SQL, PENDO_CSV, WAREHOUSE_CSV

DATABRICKS_ENV = ("DATABRICKS_SERVER_HOSTNAME", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN")


def load_demo_pendo(path: Path = PENDO_CSV) -> pd.DataFrame:
    return pd.read_csv(path)


def load_demo_databricks(path: Path = DATABRICKS_CSV) -> pd.DataFrame:
    return pd.read_csv(path)


def load_warehouse_events(path: Path = WAREHOUSE_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["event_ts"] = pd.to_datetime(df["event_ts"])
    return df


def feature_usage_sql(path: Path = FEATURE_USAGE_SQL) -> str:
    return path.read_text(encoding="utf-8")


def run_sql_locally(sql: str, events: pd.DataFrame, table_name: str = "product_events") -> pd.DataFrame:
    """Execute the warehouse query against a DataFrame with DuckDB.

    This is how the demo rollup was produced, and it is a cheap way to check that
    the SQL is valid before pointing it at a real warehouse.
    """
    import duckdb

    con = duckdb.connect()
    try:
        con.register(table_name, events)
        return con.execute(sql).df()
    finally:
        con.close()


def databricks_configured() -> bool:
    return all(os.getenv(k) for k in DATABRICKS_ENV)


def run_databricks_query(sql: str) -> pd.DataFrame:
    """Run a query on a Databricks SQL warehouse using the official connector.

    Requires `pip install databricks-sql-connector` and the three DATABRICKS_* variables.
    """
    if not databricks_configured():
        missing = [k for k in DATABRICKS_ENV if not os.getenv(k)]
        raise RuntimeError(f"Databricks is not configured; missing {missing}")
    from databricks import sql as dbsql  # optional dependency

    with dbsql.connect(
        server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
    return pd.DataFrame([tuple(r) for r in rows], columns=columns)
