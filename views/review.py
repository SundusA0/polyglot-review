"""Review workbench: one case at a time, two prompt versions side by side."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.config import ERROR_TAGS
from src.data import case_record
from src.export import build_export, now_iso, to_csv_bytes
from src.llm import LLMNotConfigured, generate_response, judge_factuality, make_client
from src.scoring import score_response
from views import common


# --------------------------------------------------------------------------- #
# Callbacks (run before widgets are instantiated, so they may set widget state)
# --------------------------------------------------------------------------- #

def _step(delta: int, case_ids: list[str]) -> None:
    ss = st.session_state
    current = ss.get("case_select")
    pos = case_ids.index(current) if current in case_ids else 0
    ss["case_select"] = case_ids[(pos + delta) % len(case_ids)]


def _next_unreviewed(case_ids: list[str]) -> None:
    ss = st.session_state
    reviewed = {a["case_id"] for a in ss["annotations"].values()}
    current = ss.get("case_select")
    pos = case_ids.index(current) if current in case_ids else -1
    order = case_ids[pos + 1:] + case_ids[: pos + 1]
    for cid in order:
        if cid not in reviewed:
            ss["case_select"] = cid
            return
    st.toast("Every case in this filter has an annotation.")


def _queue_generation(case_id: str, version: str) -> None:
    """Remember what to generate; the actual API call happens at the top of the next run."""
    ss = st.session_state
    target = version if version.endswith("-live") else f"{version}-live"
    ss["_pending_generation"] = (case_id, version, target)
    ss["review_vb"] = target


# --------------------------------------------------------------------------- #
# Live generation / judging
# --------------------------------------------------------------------------- #

def _run_pending_generation() -> None:
    ss = st.session_state
    pending = ss.pop("_pending_generation", None)
    if not pending:
        return
    case_id, version, target = pending
    base_version = version[:-5] if version.endswith("-live") else version
    key, model = common.llm_settings()
    case = case_record(common.cases_df(), case_id)
    try:
        client = make_client(key)
        with st.spinner(f"Generating {target} for {case_id} with {model}…"):
            text = generate_response(client, model, base_version, case, common.glossary())
    except LLMNotConfigured as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # network / auth / model errors surface in the UI
        st.error(f"OpenAI call failed: {exc}")
        return
    existing = ss["responses_extra"]
    n = int((existing["case_id"] == case_id).sum()) if not existing.empty else 0
    row = pd.DataFrame([{
        "response_id": f"{case_id}-{target}-{n + 1}",
        "case_id": case_id,
        "prompt_version": target,
        "source": f"openai:{model}",
        "response": text,
        "injected_errors": "",
        "generated_at": now_iso(),
    }])
    ss["responses_extra"] = pd.concat([existing, row], ignore_index=True) if not existing.empty else row
    st.toast(f"Generated {target} for {case_id}")


def _judge(case: dict, rec: dict) -> None:
    key, model = common.llm_settings()
    try:
        client = make_client(key)
        with st.spinner(f"Asking {model} to grade…"):
            result = judge_factuality(client, model, case, rec["response"])
    except Exception as exc:
        st.error(f"Judge call failed: {exc}")
        return
    st.session_state["judge"][rec["response_id"]] = result
    st.rerun()


# --------------------------------------------------------------------------- #
# Panels
# --------------------------------------------------------------------------- #

def _case_panel(case: dict, glossary) -> None:
    rtl = bool(case["rtl"])
    with st.container(border=True):
        a, b, c = st.columns([1.2, 2, 1])
        a.markdown(f"**Language:** {case['language_name']} (`{case['language']}`)")
        b.markdown(f"**Scenario:** {case['scenario_title']}")
        done, total = common.review_progress()
        c.markdown(f"<span class='pr-muted'>{done}/{total} cases reviewed</span>", unsafe_allow_html=True)

        st.markdown("**Employee question**")
        common.text_block(case["question"], rtl)
        with st.expander("Policy context the assistant was given (ground truth)"):
            common.text_block(case["context"], rtl)
        st.markdown("**Reference answer**")
        common.text_block(case["reference_answer"], rtl)

        k, t = st.columns(2)
        with k:
            st.markdown("**Key facts to cover**")
            common.chips(case["key_facts_list"])
        with t:
            st.markdown("**Required terminology**")
            items = []
            for concept in case["required_concepts_list"]:
                entry = glossary.entry(concept, case["language"])
                if entry is None:
                    continue
                avoid = f"  (not: {', '.join(entry.avoid)})" if entry.avoid else ""
                items.append(f"{entry.canonical}{avoid}")
            common.chips(items)


def _annotation_form(case: dict, rec: dict, suggested: list[str], slot: str = "") -> None:
    ss = st.session_state
    rid = rec["response_id"]
    existing = ss["annotations"].get(rid)
    with st.form(key=f"form_{slot}{rid}", border=True):
        st.markdown("**Reviewer annotation**")
        c1, c2 = st.columns(2)
        hf_default = existing.get("human_factuality") if existing else None
        fl_default = existing.get("human_fluency") if existing else None
        hf = c1.segmented_control("Factuality (1–5)", [1, 2, 3, 4, 5], default=int(hf_default) if hf_default else None,
                                  key=f"hf_{slot}{rid}",
                                  help="1 = wrong or off-policy, 5 = every claim supported and nothing important missing")
        fl = c2.segmented_control("Fluency (1–5)", [1, 2, 3, 4, 5], default=int(fl_default) if fl_default else None,
                                  key=f"fl_{slot}{rid}",
                                  help="How natural the answer reads to a native speaker of the target language")
        proposed = common.tags_of(existing) if existing else suggested
        default_tags = [t for t in proposed if t in ERROR_TAGS]
        tags = st.multiselect("Error tags (pre-filled from the heuristics; edit freely)", ERROR_TAGS,
                              default=default_tags, key=f"tags_{slot}{rid}")
        notes = st.text_area("Notes", value=(existing or {}).get("notes", ""), height=80, key=f"notes_{slot}{rid}")
        submitted = st.form_submit_button("Save annotation", type="primary")
    if submitted:
        if hf is None:
            st.warning("Pick a factuality score before saving.")
            return
        ss["annotations"][rid] = {
            "response_id": rid,
            "case_id": case["case_id"],
            "reviewer": ss.get("reviewer", "") or "anonymous",
            "human_factuality": int(hf),
            "human_fluency": int(fl) if fl is not None else None,
            "tags": "|".join(tags),
            "notes": notes.strip(),
            "reviewed_at": now_iso(),
        }
        common.persist_annotations()
        st.toast(f"Saved annotation for {rid}")
        st.rerun()


def _response_panel(case: dict, version: str, slot: str, responses: pd.DataFrame, glossary, llm_ready: bool) -> None:
    labels = common.version_labels()
    st.markdown(f"#### {slot} · {labels.get(version, version)}")
    rows = responses[(responses["case_id"] == case["case_id"]) & (responses["prompt_version"] == version)]
    if rows.empty:
        st.info("No response for this version yet.")
        if llm_ready:
            st.button("Generate with OpenAI", key=f"gen_{slot}_{version}", on_click=_queue_generation,
                      args=(case["case_id"], version))
        return

    rec = rows.iloc[-1].to_dict()
    scores = score_response(case, rec["response"], glossary)
    rtl = bool(case["rtl"])
    st.caption(f"`{rec['response_id']}` · source: {rec['source']} · {rec['generated_at'][:10]}")
    common.highlighted_response(rec["response"], scores, rtl)
    st.caption("green = key fact · blue = preferred term · red = discouraged term · yellow = number not in the policy")

    m1, m2, m3 = st.columns(3)
    m1.metric("Factuality (auto)", f"{scores.factuality.score}")
    m2.metric("Terminology (auto)", f"{scores.terminology.score}")
    detected = scores.language.detected or "?"
    m3.metric("Language", f"{detected} {'✓' if scores.language.ok else '✗'}")
    common.tag_badges(scores.suggested_tags)

    with st.expander("Scoring details"):
        f = scores.factuality
        t = scores.terminology
        st.markdown(
            f"- Facts found: {', '.join(f.facts_found) or '—'}\n"
            f"- Facts missing: {', '.join(f.facts_missing) or '—'}\n"
            f"- Numbers not in the policy or reference: {', '.join(f.numeric_conflicts) or '—'}\n"
            f"- Preferred terms used: {', '.join(f'{c} → {v}' for c, v in t.found.items()) or '—'}\n"
            f"- Preferred terms missing: {', '.join(t.missing) or '—'}\n"
            f"- Discouraged terms used: {', '.join(term for _, term in t.avoid_hits) or '—'}\n"
            f"- Detected language: {detected} (confidence {scores.language.confidence:.2f}); "
            f"English passage: {'yes' if scores.language.english_passage else 'no'}\n"
            f"- Ends mid-sentence: {'yes' if scores.truncated else 'no'}"
        )
        if rec.get("source") == "synthetic":
            injected = rec.get("injected_errors") or "none"
            st.markdown(f"- Injected errors (synthetic ground truth): `{injected}`")

    judge = st.session_state["judge"].get(rec["response_id"])
    if judge:
        score = judge.get("score")
        st.markdown(f"**LLM judge ({judge.get('model', '')}):** {score if score is not None else '?'}/5 — {judge.get('rationale', '')}")
        if judge.get("unsupported_claims"):
            st.markdown("Unsupported: " + "; ".join(judge["unsupported_claims"]))
        if judge.get("missing_facts"):
            st.markdown("Missing: " + "; ".join(judge["missing_facts"]))
    if llm_ready:
        b1, b2 = st.columns(2)
        if b1.button("Score with LLM judge", key=f"judge_{slot}_{rec['response_id']}"):
            _judge(case, rec)
        b2.button("Regenerate with OpenAI", key=f"regen_{slot}_{version}", on_click=_queue_generation,
                  args=(case["case_id"], version))

    _annotation_form(case, rec, scores.suggested_tags, slot)


def _preference_form(case: dict, va: str, vb: str) -> None:
    ss = st.session_state
    existing = ss["case_prefs"].get(case["case_id"])
    options = ["A", "B", "Tie", "Unsure"]
    idx = options.index(existing["preferred"]) if existing and existing.get("preferred") in options else None
    with st.form(key=f"pref_{case['case_id']}", border=True):
        c1, c2 = st.columns([3, 1])
        choice = c1.radio(f"Which answer is better overall? (A = {va}, B = {vb})", options, horizontal=True, index=idx)
        submitted = c2.form_submit_button("Save preference")
    if submitted:
        if choice is None:
            st.warning("Pick an option first.")
            return
        ss["case_prefs"][case["case_id"]] = {
            "case_id": case["case_id"], "version_a": va, "version_b": vb, "preferred": choice,
            "reviewer": ss.get("reviewer", "") or "anonymous", "reviewed_at": now_iso(),
        }
        common.persist_annotations()
        st.toast("Preference saved")


def _export_section(cases: pd.DataFrame) -> None:
    st.divider()
    st.subheader("Export")
    only_annotated = st.toggle("Only rows with a human annotation", value=False, key="export_only_annotated")
    export_df = build_export(
        common.scored_responses(), cases, st.session_state["annotations"], st.session_state["judge"],
        st.session_state["case_prefs"], only_annotated=only_annotated,
    )
    annotated = int((export_df["reviewed_at"].fillna("") != "").sum())
    c1, c2 = st.columns([1, 3])
    c1.download_button(
        "Download annotated CSV", data=to_csv_bytes(export_df),
        file_name=f"review_export_{date.today().isoformat()}.csv", mime="text/csv", type="primary",
    )
    c2.caption(
        f"{len(export_df)} rows · {annotated} with human scores · one row per response with auto scores, "
        "judge output, tags, notes and the preferred version. Encoded as UTF-8 with BOM so Excel opens "
        "Arabic and Japanese correctly."
    )
    with st.expander("Preview"):
        st.dataframe(export_df.head(50), hide_index=True, width="stretch", height=300)


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def render() -> None:
    common.init_state()
    common.inject_css()
    _run_pending_generation()

    cases = common.cases_df()
    glossary = common.glossary()
    responses = common.all_responses()
    ss = st.session_state

    # Sidebar
    st.sidebar.text_input("Reviewer name", key="reviewer", placeholder="your name")
    languages = sorted(cases["language"].unique())
    names = dict(zip(cases["language"], cases["language_name"]))
    sel = st.sidebar.multiselect("Languages", languages, default=languages, key="review_langs",
                                 format_func=lambda c: f"{names[c]} ({c})")
    versions = common.available_versions()
    preferred_a = "v2-live" if "v2-live" in versions else versions[0]
    preferred_b = "v3-live" if "v3-live" in versions else versions[min(1, len(versions) - 1)]
    if ss.get("review_vb") not in versions:
        ss["review_vb"] = preferred_b
    if ss.get("review_va") not in versions:
        ss["review_va"] = preferred_a
    labels = common.version_labels()
    st.sidebar.selectbox("Version A", versions, key="review_va", format_func=lambda v: labels.get(v, v))
    st.sidebar.selectbox("Version B", versions, key="review_vb", format_func=lambda v: labels.get(v, v))
    only_unreviewed = st.sidebar.toggle("Only unreviewed cases", value=False, key="review_only_unreviewed")
    common.sidebar_llm_box()
    key, _ = common.llm_settings()
    llm_ready = bool(key)

    st.title("Review")
    if common.public_demo():
        st.caption("Public demo: annotations remain in your browser session only; live API calls are disabled.")
    if ss["review_va"].endswith("-live") and ss["review_vb"].endswith("-live"):
        st.info("Showing actual model-generated answers to fictional HR policies. Compare the glossary-grounded and stricter prompt versions; inspect missing key facts below each answer.")
    else:
        st.info("Showing constructed validation examples. Switch to v2-live and v3-live to inspect the real Gemini experiment.")

    # Case list
    filtered = cases[cases["language"].isin(sel)]
    reviewed = {a["case_id"] for a in ss["annotations"].values()}
    if only_unreviewed:
        filtered = filtered[~filtered["case_id"].isin(reviewed)]
    case_ids = list(filtered["case_id"])
    if not case_ids:
        st.info("No cases match the current filters.")
        return
    if ss.get("case_select") not in case_ids:
        ss["case_select"] = case_ids[0]

    def label(cid: str) -> str:
        row = cases.loc[cases["case_id"] == cid].iloc[0]
        mark = "✓ " if cid in reviewed else "○ "
        return f"{mark}{row['scenario_title']} · {row['language_name']}"

    h1, h2, h3, h4 = st.columns([4, 1, 1, 1.6])
    h1.selectbox("Case", case_ids, key="case_select", format_func=label)
    h2.button("◀ Prev", on_click=_step, args=(-1, case_ids), width="stretch")
    h3.button("Next ▶", on_click=_step, args=(1, case_ids), width="stretch")
    h4.button("Next unreviewed", on_click=_next_unreviewed, args=(case_ids,), width="stretch")

    case = case_record(cases, ss["case_select"])
    _case_panel(case, glossary)

    va, vb = ss["review_va"], ss["review_vb"]
    col_a, col_b = st.columns(2)
    with col_a:
        _response_panel(case, va, "A", responses, glossary, llm_ready)
    with col_b:
        _response_panel(case, vb, "B", responses, glossary, llm_ready)

    _preference_form(case, va, vb)
    _export_section(cases)
