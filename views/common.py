"""Shared state, cached loaders and small rendering helpers for the pages."""
from __future__ import annotations

import html
import re

import pandas as pd
import streamlit as st

from src import config
from src.data import Glossary, load_cases, load_glossary, load_prompt_versions, load_responses, split_list
from src.export import annotations_frame, preferences_frame
from src.llm import resolve_api_key, resolve_model
from src.scoring import ReviewScores, score_table
from src.textnorm import script_shares

RESPONSE_COLUMNS = ["response_id", "case_id", "prompt_version", "source", "response", "injected_errors", "generated_at"]

TAG_COLORS = {
    "omission": "orange",
    "wrong_number": "red",
    "terminology_mismatch": "blue",
    "wrong_language": "red",
    "untranslated_text": "violet",
    "truncated": "orange",
    "hallucination": "red",
    "formatting": "gray",
    "tone": "gray",
    "other": "gray",
}

CSS = """
<style>
.pr-text { line-height: 1.6; font-size: 1.0rem; padding: 0.6rem 0.8rem; border-radius: 8px;
           background: rgba(128,128,128,0.08); }
.pr-text[dir="rtl"] { text-align: right; }
.pr-text mark { padding: 0 0.15em; border-radius: 3px; color: #111; }
.pr-text mark.fact { background: #c6f1d6; }
.pr-text mark.term { background: #cfe3ff; }
.pr-text mark.avoid { background: #ffc9c9; text-decoration: line-through; }
.pr-text mark.num { background: #ffe39a; }
.pr-chip { display: inline-block; padding: 0.1rem 0.5rem; margin: 0 0.3rem 0.3rem 0; border-radius: 999px;
           font-size: 0.85rem; background: rgba(128,128,128,0.15); }
.pr-muted { opacity: 0.7; font-size: 0.9rem; }
</style>
"""


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #

def init_state() -> None:
    ss = st.session_state
    ss.setdefault("annotations", {})       # response_id -> annotation dict
    ss.setdefault("case_prefs", {})        # case_id -> {version_a, version_b, preferred, ...}
    ss.setdefault("judge", {})             # response_id -> judge result
    ss.setdefault("reviewer", "")
    ss.setdefault("openai_key_override", "")
    ss.setdefault("openai_model_override", "")
    ss.setdefault("responses_extra", pd.DataFrame(columns=RESPONSE_COLUMNS))
    if not ss.get("_annotations_loaded"):
        _load_annotations_from_disk()
        ss["_annotations_loaded"] = True


def _load_annotations_from_disk() -> None:
    ss = st.session_state
    if config.ANNOTATIONS_CSV.exists():
        try:
            df = pd.read_csv(config.ANNOTATIONS_CSV, dtype=str).fillna("")
            for rec in df.to_dict("records"):
                for col in ("human_factuality", "human_fluency"):
                    rec[col] = int(float(rec[col])) if rec.get(col) not in ("", None) else None
                ss["annotations"][rec["response_id"]] = rec
        except Exception:  # a corrupted file should never block the app
            pass
    if config.PREFERENCES_CSV.exists():
        try:
            df = pd.read_csv(config.PREFERENCES_CSV, dtype=str).fillna("")
            for rec in df.to_dict("records"):
                ss["case_prefs"][rec["case_id"]] = rec
        except Exception:
            pass


def persist_annotations() -> None:
    """Write the session's annotations to annotations/ so a page refresh doesn't lose work."""
    config.ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    annotations_frame(st.session_state["annotations"]).to_csv(config.ANNOTATIONS_CSV, index=False)
    preferences_frame(st.session_state["case_prefs"]).to_csv(config.PREFERENCES_CSV, index=False)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def cases_df() -> pd.DataFrame:
    return load_cases()


@st.cache_data(show_spinner=False)
def responses_df() -> pd.DataFrame:
    """Synthetic demo responses, plus real model responses from scripts/run_live_eval.py if present."""
    base = load_responses()
    if config.LIVE_RESPONSES_CSV.exists():
        live = pd.read_csv(config.LIVE_RESPONSES_CSV, dtype=str).fillna("")
        for col in RESPONSE_COLUMNS:
            if col not in live.columns:
                live[col] = ""
        base = pd.concat([base, live[RESPONSE_COLUMNS]], ignore_index=True)
    return base


@st.cache_resource(show_spinner=False)
def glossary() -> Glossary:
    return load_glossary()


@st.cache_data(show_spinner=False)
def prompt_versions() -> list[dict]:
    return load_prompt_versions()


def all_responses() -> pd.DataFrame:
    """Bundled synthetic responses plus anything generated live this session."""
    extra = st.session_state.get("responses_extra")
    base = responses_df()
    if extra is None or extra.empty:
        return base
    return pd.concat([base, extra[RESPONSE_COLUMNS]], ignore_index=True)


def scored_responses() -> pd.DataFrame:
    return score_table(all_responses(), cases_df(), glossary())


def version_labels() -> dict[str, str]:
    labels = {v["version"]: f"{v['version']} · {v['name']}" for v in prompt_versions()}
    for v in sorted(all_responses()["prompt_version"].unique()):
        base = v[:-5] if v.endswith("-live") else v
        if v.endswith("-live") and base in labels:
            labels[v] = f"{labels[base]} (real model)"
        labels.setdefault(v, v)
    return labels


def available_versions() -> list[str]:
    known = [v["version"] for v in prompt_versions()]
    present = list(all_responses()["prompt_version"].unique())
    ordered = [v for v in known if v in present] + sorted(v for v in present if v not in known)
    return ordered


# --------------------------------------------------------------------------- #
# OpenAI settings (sidebar)
# --------------------------------------------------------------------------- #

def llm_settings():
    """Returns (api_key or None, model). Key from env or a session-only override."""
    key = resolve_api_key(st.session_state.get("openai_key_override"))
    model = resolve_model(st.session_state.get("openai_model_override"))
    return key, model


def sidebar_llm_box() -> None:
    key, model = llm_settings()
    with st.sidebar.expander("OpenAI (optional)", expanded=False):
        if key:
            st.caption(f"Live calls enabled · model `{model}`")
        else:
            st.caption("No API key found. Paste one here for this session, or set OPENAI_API_KEY in .env.")
        st.text_input("API key (session only)", type="password", key="openai_key_override")
        st.text_input("Model", key="openai_model_override", placeholder=config.DEFAULT_OPENAI_MODEL)


# --------------------------------------------------------------------------- #
# Rendering helpers
# --------------------------------------------------------------------------- #

def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def text_block(text: str, rtl: bool = False) -> None:
    direction = "rtl" if rtl else "ltr"
    body = html.escape(text).replace("\n", "<br>")
    st.markdown(f'<div class="pr-text" dir="{direction}">{body}</div>', unsafe_allow_html=True)


def _find_spans(text: str, needles: list[str], cls: str) -> list[tuple[int, int, str]]:
    spans = []
    for needle in needles:
        if not needle:
            continue
        for m in re.finditer(re.escape(needle), text, flags=re.IGNORECASE):
            spans.append((m.start(), m.end(), cls))
    return spans


def highlighted_response(text: str, scores: ReviewScores, rtl: bool = False) -> None:
    """Response text with key facts (green), preferred terms (blue), discouraged
    terms (red) and unexpected numbers (yellow) marked up.

    Direction follows the response itself rather than the case: an English answer
    to an Arabic question should still read left to right.
    """
    rtl = script_shares(text)["arabic"] >= 0.3
    spans = _find_spans(text, scores.factuality.facts_found, "fact")
    spans += _find_spans(text, list(scores.terminology.found.values()), "term")
    spans += _find_spans(text, [t for _, t in scores.terminology.avoid_hits], "avoid")
    nums = []
    for n in scores.factuality.numeric_conflicts:
        nums.append(n)
        if "." in n:
            nums.append(n.replace(".", ","))
    spans += _find_spans(text, nums, "num")

    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[tuple[int, int, str]] = []
    last_end = 0
    for start, end, cls in spans:
        if start < last_end:
            continue
        merged.append((start, end, cls))
        last_end = end

    pieces, pos = [], 0
    for start, end, cls in merged:
        pieces.append(html.escape(text[pos:start]))
        pieces.append(f'<mark class="{cls}">{html.escape(text[start:end])}</mark>')
        pos = end
    pieces.append(html.escape(text[pos:]))
    body = "".join(pieces).replace("\n", "<br>")
    direction = "rtl" if rtl else "ltr"
    st.markdown(f'<div class="pr-text" dir="{direction}">{body}</div>', unsafe_allow_html=True)


def chips(items: list[str]) -> None:
    if not items:
        st.caption("none")
        return
    st.markdown(" ".join(f'<span class="pr-chip">{html.escape(i)}</span>' for i in items), unsafe_allow_html=True)


def tag_badges(tags: list[str]) -> None:
    if not tags:
        st.markdown(":green-badge[no issues detected]")
        return
    st.markdown(" ".join(f":{TAG_COLORS.get(t, 'gray')}-badge[{t}]" for t in tags))


def score_color(score: int | float) -> str:
    if score >= 90:
        return "green"
    if score >= 70:
        return "orange"
    return "red"


def pct(x: float, digits: int = 0) -> str:
    return f"{x:.{digits}f}%"


def tags_of(annotation: dict | None) -> list[str]:
    if not annotation:
        return []
    return split_list(annotation.get("tags", ""))


def review_progress() -> tuple[int, int]:
    """(cases with at least one saved annotation, total cases)."""
    cases = cases_df()
    annotated_cases = {a["case_id"] for a in st.session_state["annotations"].values()}
    return len(annotated_cases & set(cases["case_id"])), len(cases)
