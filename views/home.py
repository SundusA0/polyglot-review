"""Overview page: what the app does, dataset at a glance, review progress."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.scoring import calibration, clean_false_positive_rate
from views import common


def render() -> None:
    common.init_state()
    common.inject_css()
    common.sidebar_llm_box()

    st.title("Polyglot Review")
    st.markdown(
        "A workbench for reviewing an LLM assistant's answers across languages, comparing prompt "
        "versions, and reading the product-usage data that tells you which languages matter."
    )

    cases = common.cases_df()
    scored = common.scored_responses()
    done, total = common.review_progress()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cases", len(cases))
    c2.metric("Languages", cases["language"].nunique())
    c3.metric("Prompt versions", scored["prompt_version"].nunique())
    c4.metric("Responses", len(scored))
    c5.metric("Cases reviewed", f"{done}/{total}")
    st.progress(done / total if total else 0.0)

    left, right = st.columns([3, 2])
    with left:
        st.subheader("How it fits together")
        st.markdown(
            """
**Review** — pick a case, see two prompt versions side by side with key facts, preferred terms and
unexpected numbers highlighted, then record a score, error tags and notes. Suggested tags come from
heuristics; the reviewer has the final say.

**Compare versions** — mean factuality and terminology scores per language and prompt version, win
rates, tag frequencies, and (for the bundled synthetic data) how well the auto-tags recover the
errors that were deliberately injected.

**Usage analytics** — a Pendo-style feature-events export and a Databricks SQL weekly rollup:
reach, unique users, events per user, week-over-week movement, locale mix, and a reconciliation of
the two sources.

Everything runs offline. Add an OpenAI key in the sidebar to regenerate a response for any prompt
version or to score a response with an LLM judge.
            """
        )
    with right:
        st.subheader("Bundled data")
        by_lang = (
            cases.groupby("language_name")["case_id"].count().rename("cases").reset_index()
        )
        st.dataframe(by_lang, hide_index=True, width="stretch")
        cal = calibration(scored)
        if not cal.empty:
            fp = clean_false_positive_rate(scored)
            st.caption(
                "The demo responses are synthetic with seeded, labelled error injection, so the scorer can be "
                f"checked against ground truth: mean auto-tag recall "
                f"{cal['recall'].mean():.2f}, false-alarm rate on clean responses {fp:.0%}."
            )

    with st.expander("Prompt versions"):
        versions = pd.DataFrame(common.prompt_versions())[["version", "name", "description", "file"]]
        st.dataframe(versions, hide_index=True, width="stretch")

    with st.expander("Glossary (preferred vs discouraged terms)"):
        gl = common.glossary().df.copy()
        gl["preferred"] = gl["preferred"].str.replace("|", " · ", regex=False)
        gl["avoid"] = gl["avoid"].fillna("").str.replace("|", " · ", regex=False)
        st.dataframe(gl[["concept", "language", "preferred", "avoid"]], hide_index=True, width="stretch", height=320)
