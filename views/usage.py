"""Usage analytics: Pendo feature-events export + Databricks weekly rollup."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import analytics, sources
from src.export import to_csv_bytes
from src.llm import make_client, narrate_usage
from views import charts, common

ASSISTANT_FEATURE = "Assistant Chat"


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def _demo_pendo() -> pd.DataFrame:
    return analytics.normalize_pendo(sources.load_demo_pendo())


@st.cache_data(show_spinner=False)
def _demo_databricks() -> pd.DataFrame:
    return analytics.normalize_databricks(sources.load_demo_databricks())


@st.cache_data(show_spinner=False)
def _local_sql_rollup(sql: str) -> pd.DataFrame:
    events = sources.load_warehouse_events()
    return analytics.normalize_databricks(sources.run_sql_locally(sql, events))


@st.cache_data(show_spinner=False)
def _parse_upload(raw: bytes, kind: str) -> pd.DataFrame:
    import io

    df = pd.read_csv(io.BytesIO(raw))
    return analytics.normalize_pendo(df) if kind == "pendo" else analytics.normalize_databricks(df)


def _sidebar_sources() -> tuple[pd.DataFrame | None, pd.DataFrame | None, str]:
    """Returns (pendo_df, databricks_df, sql_text). Either frame may be None if loading failed."""
    st.sidebar.markdown("**Pendo feature events**")
    pendo_src = st.sidebar.radio("Pendo source", ["Demo export", "Upload CSV"], key="pendo_src",
                                 label_visibility="collapsed", horizontal=True)
    pendo = None
    if pendo_src == "Demo export":
        pendo = _demo_pendo()
    else:
        up = st.sidebar.file_uploader("Pendo CSV (Visitor ID, Account ID, Feature, Day, Number of Events…)",
                                      type=["csv"], key="pendo_upload")
        if up is not None:
            try:
                pendo = _parse_upload(up.getvalue(), "pendo")
            except ValueError as exc:
                st.sidebar.error(str(exc))

    st.sidebar.markdown("**Databricks SQL results**")
    options = ["Demo query results", "Upload CSV", "Run SQL locally (DuckDB)", "Live Databricks query"]
    dbx_src = st.sidebar.radio("Databricks source", options, key="dbx_src", label_visibility="collapsed")
    sql = sources.feature_usage_sql()
    dbx = None
    if dbx_src == "Demo query results":
        dbx = _demo_databricks()
    elif dbx_src == "Upload CSV":
        up = st.sidebar.file_uploader("Query result CSV (week_start, feature_name, channel, events, unique_users)",
                                      type=["csv"], key="dbx_upload")
        if up is not None:
            try:
                dbx = _parse_upload(up.getvalue(), "databricks")
            except ValueError as exc:
                st.sidebar.error(str(exc))
    elif dbx_src == "Run SQL locally (DuckDB)":
        sql = st.sidebar.text_area("SQL (runs against data/warehouse_events.csv)", value=sql, height=220, key="dbx_sql_local")
        try:
            dbx = _local_sql_rollup(sql)
        except Exception as exc:
            st.sidebar.error(f"DuckDB error: {exc}")
    else:
        if sources.databricks_configured():
            sql = st.sidebar.text_area("SQL", value=sql, height=220, key="dbx_sql_live")
            if st.sidebar.button("Run on Databricks", key="dbx_run"):
                try:
                    with st.spinner("Querying the SQL warehouse…"):
                        st.session_state["dbx_live"] = analytics.normalize_databricks(sources.run_databricks_query(sql))
                except Exception as exc:
                    st.sidebar.error(f"Databricks error: {exc}")
            dbx = st.session_state.get("dbx_live")
        else:
            st.sidebar.caption(
                "Set DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH and DATABRICKS_TOKEN in .env and install "
                "`databricks-sql-connector` to run the query live. Showing the demo rollup instead."
            )
            dbx = _demo_databricks()
    return pendo, dbx, sql


# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #

def _features_tab(pendo: pd.DataFrame, summary: pd.DataFrame, trend: pd.DataFrame) -> None:
    k = analytics.kpis(pendo)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Active users", f"{k['unique_users']:,}")
    c2.metric("Feature events", f"{k['events']:,}")
    c3.metric("Events per user", f"{k['events_per_user']:.1f}")
    c4.metric("Accounts", f"{k['accounts']:,}")
    c5.metric("Days in period", k["days"])

    spark = trend.sort_values("week").groupby("feature")["unique_users"].apply(list).rename("weekly_users")
    table = summary.merge(spark, left_on="feature", right_index=True, how="left")
    st.dataframe(
        table[["feature", "unique_users", "reach_pct", "events", "events_per_user", "minutes_per_user", "accounts",
               "quadrant", "weekly_users"]],
        hide_index=True, width="stretch",
        column_config={
            "feature": "Feature",
            "unique_users": st.column_config.NumberColumn("Unique users", format="%d"),
            "reach_pct": st.column_config.ProgressColumn("Reach", format="%.0f%%", min_value=0, max_value=100),
            "events": st.column_config.NumberColumn("Events", format="%d"),
            "events_per_user": st.column_config.NumberColumn("Events / user", format="%.2f"),
            "minutes_per_user": st.column_config.NumberColumn("Minutes / user", format="%.1f"),
            "accounts": st.column_config.NumberColumn("Accounts", format="%d"),
            "quadrant": "Pattern",
            "weekly_users": st.column_config.LineChartColumn("Weekly users", y_min=0),
        },
    )
    st.caption(
        "Reach = unique users of the feature ÷ all unique visitors in the export for the period. "
        "Pattern buckets split features at the median reach and median events per user."
    )
    st.plotly_chart(charts.reach_depth_scatter(summary), width="stretch")


def _trends_tab(trend: pd.DataFrame, summary: pd.DataFrame, weeks: list[pd.Timestamp]) -> None:
    features = list(summary["feature"])
    default = features[:5]
    sel = st.multiselect("Features", features, default=default, key="trend_features")
    metric = st.radio("Metric", ["unique_users", "events", "events_per_user"], horizontal=True, key="trend_metric",
                      format_func=lambda m: m.replace("_", " "))
    subset = trend[trend["feature"].isin(sel)]
    if subset.empty:
        st.info("Pick at least one feature.")
        return
    st.plotly_chart(charts.weekly_lines(subset, metric, f"Weekly {metric.replace('_', ' ')}"), width="stretch")
    wow = analytics.week_over_week(trend, weeks)
    if wow.empty:
        st.caption("Week-over-week needs two complete weeks in the selected period.")
    else:
        st.markdown(f"**Week over week** (unique users, {weeks[-2].date()} → {weeks[-1].date()})")
        st.dataframe(
            wow, hide_index=True, width="stretch",
            column_config={
                "feature": "Feature",
                "previous_week": st.column_config.NumberColumn("Previous week", format="%d"),
                "last_week": st.column_config.NumberColumn("Last week", format="%d"),
                "change_pct": st.column_config.NumberColumn("Change", format="%+.1f%%"),
            },
        )


def _segments_tab(pendo: pd.DataFrame, summary: pd.DataFrame) -> None:
    features = list(summary["feature"])
    default_ix = features.index(ASSISTANT_FEATURE) if ASSISTANT_FEATURE in features else 0
    feature = st.selectbox("Feature", features, index=default_ix, key="segment_feature")
    left, right = st.columns([3, 2])
    locale = analytics.locale_breakdown(pendo, feature)
    with left:
        st.plotly_chart(charts.locale_bar(locale, f"{feature}: events by locale"), width="stretch")
    with right:
        st.markdown("**Locale mix**")
        st.dataframe(locale, hide_index=True, width="stretch",
                     column_config={"language": "Locale", "unique_users": "Users", "events": "Events",
                                    "share_pct": st.column_config.NumberColumn("Share", format="%.1f%%")})
        non_en = locale[~locale["language"].str.lower().str.startswith("en")]["share_pct"].sum()
        st.caption(f"{non_en:.0f}% of {feature} events come from non-English locales.")

    conc = analytics.account_concentration(pendo)
    browser = (
        pendo.groupby("browser")["visitor_id"].nunique().rename("users").reset_index()
        .sort_values("users", ascending=False)
    )
    a, b, c = st.columns(3)
    with a:
        st.metric("Top 10% accounts' share of events", f"{conc['top_share_pct']:.0f}%",
                  help=f"{conc['top_n']} of {conc['accounts']} accounts")
        st.dataframe(conc["table"].head(10), hide_index=True, width="stretch",
                     column_config={"account_id": "Account", "events": "Events"})
    with b:
        st.markdown("**Most active users**")
        st.dataframe(analytics.power_users(pendo), hide_index=True, width="stretch",
                     column_config={"visitor_id": "Visitor", "account_id": "Account", "events": "Events",
                                    "features": "Features", "active_days": "Days"})
    with c:
        st.markdown("**Browsers**")
        st.dataframe(browser, hide_index=True, width="stretch")


def _reconciliation_tab(pendo: pd.DataFrame, dbx: pd.DataFrame | None) -> None:
    if dbx is None or dbx.empty:
        st.info("Load a Databricks rollup (demo, upload, DuckDB or live) to reconcile against Pendo.")
        return
    recon = analytics.reconcile(pendo, dbx)
    summary = analytics.reconciliation_summary(recon)
    st.markdown(
        "Pendo instruments the web app, so its numbers are compared with the warehouse's **web** channel. "
        "The warehouse also records mobile and API events, shown as the share Pendo cannot see. "
        "Weeks where the two web counts differ by more than 5% are flagged."
    )
    st.plotly_chart(charts.reconciliation_bar(summary), width="stretch")
    st.dataframe(
        summary, hide_index=True, width="stretch",
        column_config={
            "feature": "Feature",
            "pendo_events": st.column_config.NumberColumn("Pendo events", format="%d"),
            "warehouse_web_events": st.column_config.NumberColumn("Warehouse web events", format="%d"),
            "warehouse_all_events": st.column_config.NumberColumn("Warehouse all channels", format="%d"),
            "events_delta_pct": st.column_config.NumberColumn("Delta (web)", format="%+.1f%%"),
            "mobile_api_share_pct": st.column_config.NumberColumn("Mobile/API share", format="%.0f%%"),
            "flagged_weeks": st.column_config.NumberColumn("Flagged weeks", format="%d"),
        },
    )
    with st.expander("Week by week"):
        st.dataframe(recon, hide_index=True, width="stretch", height=360)
    st.session_state["_recon_summary"] = summary


def _insights_tab(summary: pd.DataFrame, wow: pd.DataFrame, locale: pd.DataFrame, conc: dict,
                  recon_summary: pd.DataFrame | None, sql: str) -> None:
    notes = analytics.insights(summary, wow, locale, conc, recon_summary, ASSISTANT_FEATURE)
    st.markdown("\n".join(f"- {n}" for n in notes))
    st.caption("Generated from rules over the current filters; paste into a status update or wiki page as a starting point.")

    key, model = common.llm_settings()
    if key:
        if st.button("Draft a stakeholder update with OpenAI", key="narrate"):
            try:
                client = make_client(key)
                with st.spinner(f"Drafting with {model}…"):
                    cols = ["feature", "unique_users", "reach_pct", "events", "events_per_user"]
                    st.session_state["_usage_narrative"] = narrate_usage(client, model, notes, summary[cols].to_string(index=False))
            except Exception as exc:
                st.error(f"OpenAI call failed: {exc}")
        if st.session_state.get("_usage_narrative"):
            st.markdown(st.session_state["_usage_narrative"])
    else:
        st.caption("Add an OpenAI key in the sidebar to draft a narrative version of these notes.")

    d1, d2 = st.columns(2)
    d1.download_button("Download feature summary CSV", data=to_csv_bytes(summary), file_name="feature_summary.csv",
                       mime="text/csv")
    d2.download_button("Download insights (markdown)", data="\n".join(f"- {n}" for n in notes).encode("utf-8"),
                       file_name="usage_insights.md", mime="text/markdown")
    with st.expander("Warehouse query behind the rollup"):
        st.code(sql, language="sql")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def render() -> None:
    common.init_state()
    common.inject_css()
    st.title("Usage analytics")

    pendo, dbx, sql = _sidebar_sources()
    common.sidebar_llm_box()
    if pendo is None or pendo.empty:
        st.info("Load a Pendo export to begin.")
        return

    dmin, dmax = pendo["day"].min().date(), pendo["day"].max().date()
    period = st.sidebar.date_input("Period", value=(dmin, dmax), min_value=dmin, max_value=dmax, key="usage_period")
    if isinstance(period, (list, tuple)) and len(period) == 2:
        start, end = period
    else:
        start, end = dmin, dmax
    pendo_p = analytics.filter_period(pendo, start, end)
    if pendo_p.empty:
        st.info("No Pendo rows in the selected period.")
        return
    dbx_p = analytics.filter_period(dbx, pd.Timestamp(start) - pd.Timedelta(days=6), end, "week_start") if dbx is not None else None

    summary = analytics.feature_summary(pendo_p)
    trend = analytics.weekly_trend(pendo_p)
    weeks = analytics.complete_weeks(pendo_p)
    wow = analytics.week_over_week(trend, weeks)
    locale = analytics.locale_breakdown(pendo_p, ASSISTANT_FEATURE if ASSISTANT_FEATURE in set(summary["feature"]) else None)
    conc = analytics.account_concentration(pendo_p)

    st.caption(f"{start} → {end} · {len(pendo_p):,} Pendo rows · "
               f"{'warehouse rollup loaded' if dbx_p is not None and not dbx_p.empty else 'no warehouse rollup'}")

    tabs = st.tabs(["Features", "Trends", "Segments", "Reconciliation", "Insights"])
    with tabs[0]:
        _features_tab(pendo_p, summary, trend)
    with tabs[1]:
        _trends_tab(trend, summary, weeks)
    with tabs[2]:
        _segments_tab(pendo_p, summary)
    with tabs[3]:
        _reconciliation_tab(pendo_p, dbx_p)
    with tabs[4]:
        recon_summary = None
        if dbx_p is not None and not dbx_p.empty:
            recon_summary = analytics.reconciliation_summary(analytics.reconcile(pendo_p, dbx_p))
        _insights_tab(summary, wow, locale, conc, recon_summary, sql)
