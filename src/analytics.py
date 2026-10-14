"""Product-usage analytics over a Pendo feature-events export and a
Databricks SQL weekly rollup.

Metric definitions (kept deliberately simple and stated in the UI):

* unique users     - distinct visitor IDs that triggered the feature in the period
* events per user  - total feature events / unique users
* reach            - unique users of the feature / unique visitors seen in the
                     whole export over the same period (percent)
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .config import FEATURE_NAME_MAP

# --------------------------------------------------------------------------- #
# Column normalisation
# --------------------------------------------------------------------------- #

PENDO_ALIASES: dict[str, list[str]] = {
    "visitor_id": ["visitor id", "visitorid", "visitor", "user id", "user_id"],
    "account_id": ["account id", "accountid", "account"],
    "feature": ["feature", "feature name", "featurename", "feature_name"],
    "page": ["page", "page name"],
    "app": ["app", "application", "app name"],
    "day": ["day", "date", "event date", "timestamp", "time", "event_date"],
    "num_events": ["number of events", "events", "numevents", "event count", "num_events"],
    "num_minutes": ["number of minutes", "minutes", "numminutes", "num_minutes"],
    "browser": ["browser", "browser name"],
    "country": ["country", "region"],
    "language": ["language", "locale", "user language"],
}

DATABRICKS_ALIASES: dict[str, list[str]] = {
    "week_start": ["week_start", "week", "week start"],
    "feature_name": ["feature_name", "feature", "feature name"],
    "product_area": ["product_area", "area", "product area"],
    "channel": ["channel", "platform"],
    "events": ["events", "event_count", "num_events"],
    "unique_users": ["unique_users", "users", "distinct_users", "dau"],
    "accounts": ["accounts", "unique_accounts", "distinct_accounts"],
}

REQUIRED_PENDO = ["visitor_id", "feature", "day"]
REQUIRED_DATABRICKS = ["week_start", "feature_name", "events", "unique_users"]


def _clean_header(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def _rename_with_aliases(df: pd.DataFrame, aliases: dict[str, list[str]]) -> pd.DataFrame:
    mapping = {}
    for col in df.columns:
        key = _clean_header(col)
        for canonical, names in aliases.items():
            if key == canonical or key in names:
                mapping[col] = canonical
                break
    return df.rename(columns=mapping)


def normalize_pendo(df: pd.DataFrame) -> pd.DataFrame:
    """Accept a Pendo-style export with friendly headers and return canonical columns."""
    out = _rename_with_aliases(df.copy(), PENDO_ALIASES)
    missing = [c for c in REQUIRED_PENDO if c not in out.columns]
    if missing:
        raise ValueError(f"Pendo export is missing columns: {missing}. Found: {list(df.columns)}")
    if "num_events" not in out.columns:
        out["num_events"] = 1
    if "num_minutes" not in out.columns:
        out["num_minutes"] = np.nan
    for col in ("account_id", "page", "app", "browser", "country", "language"):
        if col not in out.columns:
            out[col] = "unknown"
    out["day"] = pd.to_datetime(out["day"], errors="coerce").dt.normalize()
    out = out.dropna(subset=["day"])
    out["num_events"] = pd.to_numeric(out["num_events"], errors="coerce").fillna(0).astype(int)
    out["num_minutes"] = pd.to_numeric(out["num_minutes"], errors="coerce")
    out["feature"] = out["feature"].astype(str).map(lambda f: FEATURE_NAME_MAP.get(f, f))
    out["week"] = week_start(out["day"])
    return out


def normalize_databricks(df: pd.DataFrame) -> pd.DataFrame:
    out = _rename_with_aliases(df.copy(), DATABRICKS_ALIASES)
    missing = [c for c in REQUIRED_DATABRICKS if c not in out.columns]
    if missing:
        raise ValueError(f"Query result is missing columns: {missing}. Found: {list(df.columns)}")
    out["week_start"] = pd.to_datetime(out["week_start"], errors="coerce").dt.normalize()
    out = out.dropna(subset=["week_start"])
    for col in ("events", "unique_users", "accounts"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    if "channel" not in out.columns:
        out["channel"] = "all"
    if "product_area" not in out.columns:
        out["product_area"] = "unknown"
    return out


def week_start(days: pd.Series) -> pd.Series:
    """Monday of the ISO week for each date."""
    days = pd.to_datetime(days)
    return (days - pd.to_timedelta(days.dt.weekday, unit="D")).dt.normalize()


# --------------------------------------------------------------------------- #
# Pendo metrics
# --------------------------------------------------------------------------- #

def filter_period(df: pd.DataFrame, start, end, date_col: str = "day") -> pd.DataFrame:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    return df[(df[date_col] >= start) & (df[date_col] <= end)]


def kpis(pendo: pd.DataFrame) -> dict:
    users = int(pendo["visitor_id"].nunique())
    events = int(pendo["num_events"].sum())
    return {
        "unique_users": users,
        "events": events,
        "events_per_user": events / users if users else 0.0,
        "accounts": int(pendo["account_id"].nunique()),
        "features": int(pendo["feature"].nunique()),
        "days": int(pendo["day"].nunique()),
    }


def feature_summary(pendo: pd.DataFrame) -> pd.DataFrame:
    total_users = pendo["visitor_id"].nunique()
    g = (
        pendo.groupby("feature")
        .agg(unique_users=("visitor_id", "nunique"), events=("num_events", "sum"),
             accounts=("account_id", "nunique"), minutes=("num_minutes", "sum"))
        .reset_index()
    )
    g["events_per_user"] = (g["events"] / g["unique_users"]).round(2)
    g["reach_pct"] = (100 * g["unique_users"] / total_users).round(1) if total_users else 0.0
    g["minutes_per_user"] = (g["minutes"] / g["unique_users"]).round(1)
    g = g.sort_values("unique_users", ascending=False).reset_index(drop=True)
    g["quadrant"] = classify_quadrants(g)
    return g


def classify_quadrants(summary: pd.DataFrame) -> pd.Series:
    """Split features on median reach and median depth into four readable buckets."""
    if summary.empty:
        return pd.Series(dtype=str)
    reach_med = summary["reach_pct"].median()
    depth_med = summary["events_per_user"].median()
    labels = []
    for reach, depth in zip(summary["reach_pct"], summary["events_per_user"]):
        high_reach = reach >= reach_med
        high_depth = depth >= depth_med
        if high_reach and high_depth:
            labels.append("core workflow")
        elif high_reach:
            labels.append("broad, shallow")
        elif high_depth:
            labels.append("niche, deep")
        else:
            labels.append("low traction")
    return pd.Series(labels, index=summary.index)


def weekly_trend(pendo: pd.DataFrame) -> pd.DataFrame:
    g = (
        pendo.groupby(["week", "feature"])
        .agg(unique_users=("visitor_id", "nunique"), events=("num_events", "sum"))
        .reset_index()
        .sort_values(["feature", "week"])
    )
    g["events_per_user"] = (g["events"] / g["unique_users"]).round(2)
    return g


def complete_weeks(pendo: pd.DataFrame) -> list[pd.Timestamp]:
    """Weeks for which the export contains all seven days (avoids a partial final week)."""
    counts = pendo.groupby("week")["day"].nunique()
    return sorted(counts[counts >= 7].index.tolist())


def week_over_week(trend: pd.DataFrame, weeks: list[pd.Timestamp]) -> pd.DataFrame:
    """Change in unique users between the last two complete weeks, per feature."""
    if len(weeks) < 2:
        return pd.DataFrame(columns=["feature", "previous_week", "last_week", "change_pct"])
    prev_w, last_w = weeks[-2], weeks[-1]
    prev = trend[trend["week"] == prev_w].set_index("feature")["unique_users"]
    last = trend[trend["week"] == last_w].set_index("feature")["unique_users"]
    out = pd.DataFrame({"previous_week": prev, "last_week": last}).fillna(0).reset_index()
    out["change_pct"] = np.where(
        out["previous_week"] > 0,
        100 * (out["last_week"] - out["previous_week"]) / out["previous_week"],
        np.nan,
    )
    out["change_pct"] = out["change_pct"].round(1)
    return out.sort_values("change_pct", ascending=False).reset_index(drop=True)


def locale_breakdown(pendo: pd.DataFrame, feature: str | None = None) -> pd.DataFrame:
    df = pendo if feature is None else pendo[pendo["feature"] == feature]
    g = (
        df.groupby("language")
        .agg(unique_users=("visitor_id", "nunique"), events=("num_events", "sum"))
        .reset_index()
        .sort_values("events", ascending=False)
    )
    total = g["events"].sum()
    g["share_pct"] = (100 * g["events"] / total).round(1) if total else 0.0
    return g.reset_index(drop=True)


def account_concentration(pendo: pd.DataFrame, top_share: float = 0.10) -> dict:
    per_account = pendo.groupby("account_id")["num_events"].sum().sort_values(ascending=False)
    n_top = max(1, int(round(len(per_account) * top_share)))
    total = per_account.sum()
    return {
        "accounts": int(len(per_account)),
        "top_n": n_top,
        "top_share_pct": float(100 * per_account.head(n_top).sum() / total) if total else 0.0,
        "table": per_account.reset_index().rename(columns={"num_events": "events"}),
    }


def power_users(pendo: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    g = (
        pendo.groupby(["visitor_id", "account_id"])
        .agg(events=("num_events", "sum"), features=("feature", "nunique"), active_days=("day", "nunique"))
        .reset_index()
        .sort_values("events", ascending=False)
    )
    return g.head(n).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Reconciliation against the warehouse rollup
# --------------------------------------------------------------------------- #

def reconcile(pendo: pd.DataFrame, dbx: pd.DataFrame, threshold_pct: float = 5.0) -> pd.DataFrame:
    """Compare Pendo (web instrumentation) with the warehouse's web channel, per feature and week.

    Pendo only sees web sessions, so the fair comparison is against `channel == "web"`;
    the all-channel event total is carried along to show how much mobile/API activity
    the front-end instrumentation cannot see.
    """
    p = (
        pendo.groupby(["week", "feature"])
        .agg(pendo_users=("visitor_id", "nunique"), pendo_events=("num_events", "sum"))
        .reset_index()
    )
    web = dbx[dbx["channel"].astype(str).str.lower() == "web"]
    if web.empty:  # rollup without channel breakdown
        web = dbx
    w = (
        web.groupby(["week_start", "feature_name"])
        .agg(warehouse_web_users=("unique_users", "sum"), warehouse_web_events=("events", "sum"))
        .reset_index()
        .rename(columns={"week_start": "week", "feature_name": "feature"})
    )
    all_ch = (
        dbx.groupby(["week_start", "feature_name"])["events"].sum().reset_index()
        .rename(columns={"week_start": "week", "feature_name": "feature", "events": "warehouse_all_events"})
    )
    out = p.merge(w, on=["week", "feature"], how="outer").merge(all_ch, on=["week", "feature"], how="left")
    for col in ("pendo_users", "pendo_events", "warehouse_web_users", "warehouse_web_events", "warehouse_all_events"):
        out[col] = out[col].fillna(0).astype(int)
    out["users_delta_pct"] = _delta_pct(out["pendo_users"], out["warehouse_web_users"])
    out["events_delta_pct"] = _delta_pct(out["pendo_events"], out["warehouse_web_events"])
    out["mobile_api_share_pct"] = np.where(
        out["warehouse_all_events"] > 0,
        100 * (out["warehouse_all_events"] - out["warehouse_web_events"]) / out["warehouse_all_events"],
        np.nan,
    ).round(1)
    out["flag"] = out["events_delta_pct"].abs() > threshold_pct
    return out.sort_values(["feature", "week"]).reset_index(drop=True)


def _delta_pct(observed: pd.Series, expected: pd.Series) -> pd.Series:
    return pd.Series(
        np.where(expected > 0, 100 * (observed - expected) / expected, np.nan), index=observed.index
    ).round(1)


def reconciliation_summary(recon: pd.DataFrame) -> pd.DataFrame:
    g = (
        recon.groupby("feature")
        .agg(pendo_events=("pendo_events", "sum"), warehouse_web_events=("warehouse_web_events", "sum"),
             warehouse_all_events=("warehouse_all_events", "sum"), flagged_weeks=("flag", "sum"))
        .reset_index()
    )
    g["events_delta_pct"] = _delta_pct(g["pendo_events"], g["warehouse_web_events"])
    g["mobile_api_share_pct"] = np.where(
        g["warehouse_all_events"] > 0,
        100 * (g["warehouse_all_events"] - g["warehouse_web_events"]) / g["warehouse_all_events"],
        np.nan,
    ).round(1)
    return g.sort_values("events_delta_pct").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Rule-based insights
# --------------------------------------------------------------------------- #

def insights(summary: pd.DataFrame, wow: pd.DataFrame, locale: pd.DataFrame,
             concentration: dict, recon_summary: pd.DataFrame | None,
             assistant_feature: str | None = None) -> list[str]:
    """Plain-language observations a PM could paste into a status update."""
    notes: list[str] = []
    if summary.empty:
        return ["No usage rows in the selected period."]

    top = summary.iloc[0]
    notes.append(
        f"**{top['feature']}** has the widest reach: {top['reach_pct']:.0f}% of active users "
        f"({int(top['unique_users'])} people) used it, averaging {top['events_per_user']:.1f} events each."
    )
    shallow = summary[summary["quadrant"] == "broad, shallow"]
    if not shallow.empty:
        s = shallow.iloc[0]
        notes.append(
            f"**{s['feature']}** is broad but shallow ({s['reach_pct']:.0f}% reach, {s['events_per_user']:.1f} "
            f"events/user): lots of people touch it once. Worth checking whether a single visit completes the task."
        )
    deep = summary.sort_values("events_per_user", ascending=False).iloc[0]
    notes.append(
        f"**{deep['feature']}** is the stickiest feature at {deep['events_per_user']:.1f} events per user "
        f"({deep['reach_pct']:.0f}% reach)."
    )
    if not wow.empty and wow["change_pct"].notna().any():
        up = wow.dropna(subset=["change_pct"]).iloc[0]
        down = wow.dropna(subset=["change_pct"]).iloc[-1]
        if up["change_pct"] > 0:
            notes.append(
                f"Fastest week-over-week growth: **{up['feature']}** ({up['change_pct']:+.0f}% unique users, "
                f"{int(up['previous_week'])} to {int(up['last_week'])})."
            )
        if down["change_pct"] < 0:
            notes.append(
                f"Largest week-over-week drop: **{down['feature']}** ({down['change_pct']:+.0f}% unique users)."
            )
    if not locale.empty:
        non_en = locale[~locale["language"].astype(str).str.lower().str.startswith("en")]
        share = float(non_en["share_pct"].sum())
        label = f"**{assistant_feature}** usage" if assistant_feature else "usage"
        if not non_en.empty:
            lead = non_en.iloc[0]
            notes.append(
                f"{share:.0f}% of {label} comes from non-English locales, led by **{lead['language']}** "
                f"({lead['share_pct']:.0f}%). Evaluation coverage should follow that mix."
            )
    if concentration.get("accounts"):
        notes.append(
            f"The top {concentration['top_n']} of {concentration['accounts']} accounts generate "
            f"{concentration['top_share_pct']:.0f}% of all events, so account-level feedback is not representative "
            f"of the long tail."
        )
    if recon_summary is not None and not recon_summary.empty:
        worst = recon_summary.iloc[0]
        if pd.notna(worst["events_delta_pct"]) and abs(worst["events_delta_pct"]) > 5:
            notes.append(
                f"Pendo undercounts **{worst['feature']}** web events by {abs(worst['events_delta_pct']):.0f}% "
                f"versus the warehouse, and {worst['mobile_api_share_pct']:.0f}% of that feature's events happen on "
                f"mobile or API where Pendo has no instrumentation. Treat Pendo reach for it as a floor."
            )
    return notes
