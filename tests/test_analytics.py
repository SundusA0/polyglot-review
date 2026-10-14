import pandas as pd
import pytest

from src import analytics, sources


def tiny_pendo():
    rows = [
        # visitor, account, feature, day, events, language
        ("v1", "a1", "Schedule View", "2026-09-07", 3, "en-US"),
        ("v2", "a1", "Schedule View", "2026-09-08", 1, "fr-CA"),
        ("v3", "a2", "Schedule View", "2026-09-09", 2, "en-US"),
        ("v1", "a1", "Assistant Chat", "2026-09-10", 4, "en-US"),
        ("v2", "a1", "Assistant Chat", "2026-09-11", 6, "fr-CA"),
        ("v4", "a3", "Expense Report", "2026-09-12", 1, "de-DE"),
    ]
    df = pd.DataFrame(rows, columns=["Visitor ID", "Account ID", "Feature", "Day", "Number of Events", "Language"])
    return analytics.normalize_pendo(df)


def test_pendo_header_aliases():
    df = tiny_pendo()
    assert {"visitor_id", "account_id", "feature", "day", "num_events", "language", "week"} <= set(df.columns)
    assert str(df["day"].dtype).startswith("datetime64")


def test_pendo_missing_columns_raises():
    with pytest.raises(ValueError):
        analytics.normalize_pendo(pd.DataFrame({"Feature": ["x"], "Day": ["2026-01-01"]}))


def test_feature_summary_math():
    s = analytics.feature_summary(tiny_pendo()).set_index("feature")
    # 4 distinct visitors overall; Schedule View was used by 3 of them
    assert s.loc["Schedule View", "unique_users"] == 3
    assert s.loc["Schedule View", "reach_pct"] == 75.0
    assert s.loc["Schedule View", "events"] == 6
    assert s.loc["Schedule View", "events_per_user"] == 2.0
    assert s.loc["Assistant Chat", "events_per_user"] == 5.0


def test_locale_breakdown_shares():
    loc = analytics.locale_breakdown(tiny_pendo(), "Assistant Chat").set_index("language")
    assert loc.loc["fr-CA", "share_pct"] == 60.0
    assert loc.loc["en-US", "share_pct"] == 40.0


def test_week_start_is_monday():
    ws = analytics.week_start(pd.Series(pd.to_datetime(["2026-09-09", "2026-09-13", "2026-09-14"])))
    assert [d.weekday() for d in ws] == [0, 0, 0]
    assert ws.iloc[0] == pd.Timestamp("2026-09-07")
    assert ws.iloc[2] == pd.Timestamp("2026-09-14")


def test_reconcile_flags_large_delta():
    pendo = tiny_pendo()
    dbx = analytics.normalize_databricks(pd.DataFrame({
        "week_start": ["2026-09-07", "2026-09-07", "2026-09-07"],
        "feature_name": ["Schedule View", "Schedule View", "Assistant Chat"],
        "product_area": ["Time", "Time", "Assistant"],
        "channel": ["web", "mobile", "web"],
        "events": [8, 4, 10],
        "unique_users": [4, 2, 2],
        "accounts": [2, 1, 1],
    }))
    recon = analytics.reconcile(pendo, dbx).set_index("feature")
    sched = recon.loc["Schedule View"]
    assert sched["pendo_events"] == 6 and sched["warehouse_web_events"] == 8
    assert sched["events_delta_pct"] == -25.0
    assert sched["mobile_api_share_pct"] == pytest.approx(33.3, abs=0.1)
    assert bool(sched["flag"]) is True


def test_bundled_rollup_matches_sql_run():
    events = sources.load_warehouse_events()
    fresh = sources.run_sql_locally(sources.feature_usage_sql(), events)
    bundled = sources.load_demo_databricks()
    assert len(fresh) == len(bundled)
    assert int(fresh["events"].sum()) == int(bundled["events"].sum()) == len(events)


def test_bundled_pendo_is_subset_of_warehouse_web_events():
    pendo = analytics.normalize_pendo(sources.load_demo_pendo())
    events = sources.load_warehouse_events()
    web = events[events["channel"] == "web"]
    assert pendo["num_events"].sum() < len(web)           # ad-blocked visitors are missing from Pendo
    assert pendo["num_events"].sum() > 0.9 * len(web)     # but not by much


def test_insights_mention_top_feature():
    pendo = tiny_pendo()
    summary = analytics.feature_summary(pendo)
    trend = analytics.weekly_trend(pendo)
    wow = analytics.week_over_week(trend, analytics.complete_weeks(pendo))
    locale = analytics.locale_breakdown(pendo, "Assistant Chat")
    conc = analytics.account_concentration(pendo)
    notes = analytics.insights(summary, wow, locale, conc, None, "Assistant Chat")
    assert any("Schedule View" in n for n in notes)
    assert any("non-English" in n for n in notes)
