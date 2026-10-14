"""Building the annotated export: responses + auto scores + judge + human annotations."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

ANNOTATION_COLUMNS = [
    "response_id", "case_id", "reviewer", "human_factuality", "human_fluency", "tags", "notes", "reviewed_at",
]
PREFERENCE_COLUMNS = ["case_id", "version_a", "version_b", "preferred", "reviewer", "reviewed_at"]

EXPORT_ORDER = [
    "response_id", "case_id", "scenario", "language", "language_name", "prompt_version", "source",
    "question", "reference_answer", "response",
    "factuality_auto", "fact_coverage", "facts_missing", "numeric_conflicts",
    "terminology_auto", "terms_missing", "avoid_term_hits",
    "language_detected", "language_ok", "english_passage", "truncated", "suggested_tags",
    "judge_score", "judge_rationale", "judge_unsupported_claims", "judge_model",
    "human_factuality", "human_fluency", "tags", "notes", "reviewer", "reviewed_at",
    "preferred_version", "injected_errors", "generated_at",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def annotations_frame(annotations: dict[str, dict]) -> pd.DataFrame:
    if not annotations:
        return pd.DataFrame(columns=ANNOTATION_COLUMNS)
    df = pd.DataFrame(list(annotations.values()))
    for col in ANNOTATION_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[ANNOTATION_COLUMNS]


def preferences_frame(prefs: dict[str, dict]) -> pd.DataFrame:
    if not prefs:
        return pd.DataFrame(columns=PREFERENCE_COLUMNS)
    df = pd.DataFrame(list(prefs.values()))
    for col in PREFERENCE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[PREFERENCE_COLUMNS]


def build_export(scored: pd.DataFrame, cases: pd.DataFrame, annotations: dict[str, dict],
                 judge: dict[str, dict], prefs: dict[str, dict], only_annotated: bool = False) -> pd.DataFrame:
    """Join everything on response_id. One row per response."""
    df = scored.merge(
        cases[["case_id", "question", "reference_answer"]], on="case_id", how="left"
    )
    ann = annotations_frame(annotations).drop(columns=["case_id"], errors="ignore")
    df = df.merge(ann, on="response_id", how="left")

    judge_rows = []
    for rid, j in judge.items():
        judge_rows.append({
            "response_id": rid,
            "judge_score": j.get("score"),
            "judge_rationale": j.get("rationale", ""),
            "judge_unsupported_claims": "|".join(j.get("unsupported_claims") or []),
            "judge_model": j.get("model", ""),
        })
    if judge_rows:
        df = df.merge(pd.DataFrame(judge_rows), on="response_id", how="left")

    pref_map = {}
    for case_id, p in prefs.items():
        winner = p.get("preferred")
        pref_map[case_id] = p.get(f"version_{winner.lower()}", winner) if winner in ("A", "B") else winner
    df["preferred_version"] = df["case_id"].map(pref_map)

    if only_annotated:
        df = df[df["reviewed_at"].notna() & (df["reviewed_at"] != "")]

    for col in EXPORT_ORDER:
        if col not in df.columns:
            df[col] = ""
    return df[EXPORT_ORDER].reset_index(drop=True)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    # utf-8-sig so Excel opens Arabic/Japanese cells correctly.
    return df.to_csv(index=False).encode("utf-8-sig")
