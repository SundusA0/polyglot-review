"""Prompt-version comparison: aggregate scores, win rates, tags, scorer calibration."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data import split_list
from src.export import to_csv_bytes
from src.scoring import calibration, clean_false_positive_rate
from views import charts, common

COMBINED_WEIGHTS = (0.6, 0.4)  # factuality, terminology


def _combined(df: pd.DataFrame) -> pd.Series:
    wf, wt = COMBINED_WEIGHTS
    return wf * df["factuality_auto"] + wt * df["terminology_auto"]


def _aggregate(scored: pd.DataFrame) -> pd.DataFrame:
    df = scored.copy()
    df["any_tag"] = df["suggested_tags"] != ""
    df["wrong_language"] = df["suggested_tags"].str.contains("wrong_language")
    agg = (
        df.groupby(["prompt_version", "language", "language_name"])
        .agg(responses=("response_id", "count"),
             factuality=("factuality_auto", "mean"),
             terminology=("terminology_auto", "mean"),
             flagged_pct=("any_tag", "mean"),
             wrong_language_pct=("wrong_language", "mean"))
        .reset_index()
    )
    agg["flagged_pct"] = (100 * agg["flagged_pct"]).round(0)
    agg["wrong_language_pct"] = (100 * agg["wrong_language_pct"]).round(0)
    agg["factuality"] = agg["factuality"].round(1)
    agg["terminology"] = agg["terminology"].round(1)
    return agg


def _win_rates(scored: pd.DataFrame, va: str, vb: str, annotations: dict, prefs: dict) -> dict:
    a = scored[scored["prompt_version"] == va].drop_duplicates("case_id", keep="last").set_index("case_id")
    b = scored[scored["prompt_version"] == vb].drop_duplicates("case_id", keep="last").set_index("case_id")
    shared = a.index.intersection(b.index)
    ca, cb = _combined(a.loc[shared]), _combined(b.loc[shared])
    diff = (ca - cb).round(3)
    auto = {"A": int((diff > 0).sum()), "B": int((diff < 0).sum()), "Tie": int((diff == 0).sum()), "n": len(shared)}

    # Human scores where both versions were annotated.
    human = {"A": 0, "B": 0, "Tie": 0, "n": 0}
    for cid in shared:
        ha = annotations.get(a.loc[cid, "response_id"], {}).get("human_factuality")
        hb = annotations.get(b.loc[cid, "response_id"], {}).get("human_factuality")
        if ha is None or hb is None:
            continue
        human["n"] += 1
        if ha > hb:
            human["A"] += 1
        elif hb > ha:
            human["B"] += 1
        else:
            human["Tie"] += 1

    stated = {"A": 0, "B": 0, "Tie": 0, "Unsure": 0, "n": 0}
    for cid, p in prefs.items():
        if {p.get("version_a"), p.get("version_b")} == {va, vb} and p.get("preferred") in stated:
            choice = p["preferred"]
            if p.get("version_a") != va and choice in ("A", "B"):  # recorded with the versions swapped
                choice = "B" if choice == "A" else "A"
            stated[choice] += 1
            stated["n"] += 1
    per_case = pd.DataFrame({
        "case_id": shared,
        f"{va} combined": ca.values.round(1),
        f"{vb} combined": cb.values.round(1),
        "difference": diff.values,
    }).sort_values("difference")
    return {"auto": auto, "human": human, "stated": stated, "per_case": per_case}


def _tag_counts(scored: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for rec in scored.to_dict("records"):
        for tag in split_list(rec["suggested_tags"]):
            rows.append({"prompt_version": rec["prompt_version"], "tag": tag})
    if not rows:
        return pd.DataFrame(columns=["prompt_version", "tag", "count"])
    return pd.DataFrame(rows).groupby(["prompt_version", "tag"]).size().rename("count").reset_index()


def _win_box(title: str, counts: dict, va: str, vb: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        n = counts.get("n", 0)
        if not n:
            st.caption("no data yet")
            return
        cols = st.columns(3 if "Unsure" not in counts else 4)
        cols[0].metric(f"A · {va}", f"{100 * counts['A'] / n:.0f}%", help=f"{counts['A']} of {n} cases")
        cols[1].metric(f"B · {vb}", f"{100 * counts['B'] / n:.0f}%", help=f"{counts['B']} of {n} cases")
        cols[2].metric("Tie", f"{100 * counts['Tie'] / n:.0f}%", help=f"{counts['Tie']} of {n} cases")
        if "Unsure" in counts:
            cols[3].metric("Unsure", f"{counts['Unsure']}")
        st.caption(f"{n} cases · A wins {counts['A']}, B wins {counts['B']}, ties {counts['Tie']}")


def render() -> None:
    common.init_state()
    common.inject_css()
    common.sidebar_llm_box()
    st.title("Compare versions")

    scored = common.scored_responses()
    versions = common.available_versions()
    labels = common.version_labels()
    ss = st.session_state

    cases = common.cases_df()
    languages = sorted(cases["language"].unique())
    names = dict(zip(cases["language"], cases["language_name"]))
    sel = st.sidebar.multiselect("Languages", languages, default=languages, key="compare_langs",
                                 format_func=lambda c: f"{names[c]} ({c})")
    scored = scored[scored["language"].isin(sel)]
    if scored.empty:
        st.info("No responses for the selected languages.")
        return

    c1, c2 = st.columns(2)
    if ss.get("compare_va") not in versions:
        ss["compare_va"] = versions[0]
    if ss.get("compare_vb") not in versions:
        ss["compare_vb"] = versions[min(1, len(versions) - 1)]
    va = c1.selectbox("Version A", versions, key="compare_va", format_func=lambda v: labels.get(v, v))
    vb = c2.selectbox("Version B", versions, key="compare_vb", format_func=lambda v: labels.get(v, v))

    # --- Aggregate scores -------------------------------------------------- #
    st.subheader("Average scores by language")
    agg = _aggregate(scored)
    agg_ab = agg[agg["prompt_version"].isin([va, vb])] if va != vb else agg[agg["prompt_version"] == va]
    k1, k2 = st.columns(2)
    k1.plotly_chart(charts.version_metric_bars(agg_ab, "factuality", "Factuality (auto, 0-100)"), width="stretch")
    k2.plotly_chart(charts.version_metric_bars(agg_ab, "terminology", "Terminology (auto, 0-100)"), width="stretch")

    overall = (
        scored.groupby("prompt_version")
        .agg(responses=("response_id", "count"), factuality=("factuality_auto", "mean"),
             terminology=("terminology_auto", "mean"),
             flagged_pct=("suggested_tags", lambda s: 100 * (s != "").mean()))
        .reset_index()
    )
    overall["combined"] = (COMBINED_WEIGHTS[0] * overall["factuality"] + COMBINED_WEIGHTS[1] * overall["terminology"])
    st.dataframe(
        overall.round(1).rename(columns={"prompt_version": "version", "flagged_pct": "responses flagged (%)"}),
        hide_index=True, width="stretch",
    )
    st.caption(
        f"Combined = {COMBINED_WEIGHTS[0]:.0%} factuality + {COMBINED_WEIGHTS[1]:.0%} terminology. "
        "Auto scores are heuristic: factuality is key-fact coverage minus a penalty for numbers that do not appear "
        "in the policy; terminology is preferred-term coverage minus a penalty for discouraged terms."
    )
    with st.expander("Per language table"):
        st.dataframe(
            agg[agg["prompt_version"].isin([va, vb])].rename(columns={"flagged_pct": "flagged (%)", "wrong_language_pct": "wrong language (%)"}),
            hide_index=True, width="stretch",
        )

    # --- Win rates ---------------------------------------------------------- #
    st.subheader(f"Head to head: {va} vs {vb}")
    if va == vb:
        st.info("Pick two different versions to see win rates.")
    else:
        wins = _win_rates(scored, va, vb, ss["annotations"], ss["case_prefs"])
        w1, w2, w3 = st.columns(3)
        with w1:
            _win_box("Auto combined score", wins["auto"], va, vb)
        with w2:
            _win_box("Human factuality (both annotated)", wins["human"], va, vb)
        with w3:
            _win_box("Reviewer's stated preference", wins["stated"], va, vb)
        with st.expander("Per case differences"):
            st.dataframe(wins["per_case"], hide_index=True, width="stretch", height=300)

    # --- Tags --------------------------------------------------------------- #
    st.subheader("Suggested error tags")
    tag_counts = _tag_counts(scored)
    if tag_counts.empty:
        st.caption("No tags suggested for the current selection.")
    else:
        st.plotly_chart(charts.tag_frequency_bars(tag_counts), width="stretch")

    # --- Calibration -------------------------------------------------------- #
    st.subheader("Scorer calibration (synthetic data only)")
    cal = calibration(scored)
    if cal.empty or cal["injected"].sum() == 0:
        st.caption("Calibration needs synthetic responses with injected-error labels.")
    else:
        fp = clean_false_positive_rate(scored)
        st.markdown(
            "The bundled responses were generated with deliberate, labelled errors, so the heuristics can be "
            "checked against ground truth. Hallucinated *claims* are only caught when they contain a number the "
            f"policy never mentions; the rest needs the LLM judge or a human. False-alarm rate on clean "
            f"responses: **{fp:.0%}**."
        )
        cc1, cc2 = st.columns([1, 1])
        cc1.plotly_chart(charts.calibration_bars(cal.fillna(0)), width="stretch")
        cc2.dataframe(
            cal.round(2), hide_index=True, width="stretch",
            column_config={"false_alarms": "false alarms",
                           "recall": st.column_config.NumberColumn("recall", format="%.2f"),
                           "precision": st.column_config.NumberColumn("precision", format="%.2f")},
        )

    st.download_button(
        "Download aggregate CSV", data=to_csv_bytes(agg), file_name="version_comparison.csv", mime="text/csv",
    )
