"""Evaluate the prompt versions on real model output.

For every case and prompt version this sends the rendered prompt to a model,
stores the answer, optionally grades it with the LLM judge, and then scores
everything with the same heuristics the review app uses. The report compares
versions per language and, for each pair of versions, reports the paired
difference on the same cases with a bootstrap 95% confidence interval.

Unlike the bundled synthetic responses (where error rates per version were set
by the generator), these numbers say something about the prompts themselves,
within the limits stated in the report.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .data import Glossary
from .llm import generate_response, judge_factuality
from .scoring import score_table

LIVE_COLUMNS = [
    "response_id", "case_id", "prompt_version", "source", "response", "injected_errors", "generated_at",
    "judge_score", "judge_rationale", "judge_unsupported_claims", "judge_language_ok", "judge_model",
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_FATAL = ("insufficient_quota", "credit_balance", "invalid_api_key", "incorrect api key", "api key not valid",
          "permission_denied", "not found", "404")


def _with_retries(fn: Callable, attempts: int = 6, base_delay: float = 5.0, sleep=time.sleep):
    """Retry transient failures (rate limits, timeouts) with exponential backoff: 5, 10, 20, 40, 80 s.
    Errors that retrying cannot fix (bad key, no credit, unknown model) are raised immediately."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            msg = str(exc).lower()
            if i == attempts - 1 or any(f in msg for f in _FATAL):
                raise
            sleep(base_delay * (2 ** i))


def load_existing(path: Path) -> pd.DataFrame:
    if path.exists():
        df = pd.read_csv(path, dtype=str).fillna("")
        for col in LIVE_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[LIVE_COLUMNS]
    return pd.DataFrame(columns=LIVE_COLUMNS)


def run_generation(cases: pd.DataFrame, versions: list[str], client, model: str, glossary: Glossary,
                   out_path: Path, judge: bool = True, judge_model: str | None = None,
                   log: Callable[[str], None] = print, sleep=time.sleep, delay: float = 0.0,
                   provider: str = "openai") -> pd.DataFrame:
    """Generate (and judge) one answer per case and version. Resumable: rows already
    in out_path are kept and skipped, and the file is saved after every case."""
    existing = load_existing(out_path)
    done = set(zip(existing["case_id"], existing["prompt_version"]))
    rows = existing.to_dict("records")
    todo = [(c, v) for c in cases.to_dict("records") for v in versions if (c["case_id"], f"{v}-live") not in done]
    log(f"{len(done)} answers already saved, {len(todo)} to generate with {model}")

    for i, (case, version) in enumerate(todo, start=1):
        if delay and i > 1:
            sleep(delay)  # stay under free-tier requests-per-minute limits
        text = _with_retries(lambda: generate_response(client, model, version, case, glossary), sleep=sleep)
        row = {
            "response_id": f"{case['case_id']}-{version}-live",
            "case_id": case["case_id"],
            "prompt_version": f"{version}-live",
            "source": f"{provider}:{model}",
            "response": text,
            "injected_errors": "",
            "generated_at": _now(),
            "judge_score": "", "judge_rationale": "", "judge_unsupported_claims": "",
            "judge_language_ok": "", "judge_model": "",
        }
        if judge:
            jm = judge_model or model
            if delay:
                sleep(delay)
            result = _with_retries(lambda: judge_factuality(client, jm, case, text), sleep=sleep)
            row.update({
                "judge_score": "" if result.get("score") is None else str(result["score"]),
                "judge_rationale": result.get("rationale", ""),
                "judge_unsupported_claims": "|".join(result.get("unsupported_claims") or []),
                "judge_language_ok": "" if result.get("language_ok") is None else str(result["language_ok"]),
                "judge_model": jm,
            })
        rows.append(row)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=LIVE_COLUMNS).to_csv(out_path, index=False)
        log(f"[{i}/{len(todo)}] {row['response_id']}" + (f"  judge={row['judge_score']}" if judge else ""))
    return pd.DataFrame(rows, columns=LIVE_COLUMNS)


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #

def score_live(live: pd.DataFrame, cases: pd.DataFrame, glossary: Glossary) -> pd.DataFrame:
    base_cols = ["response_id", "case_id", "prompt_version", "source", "response", "injected_errors", "generated_at"]
    scored = score_table(live[base_cols], cases, glossary)
    extra = live[["response_id", "judge_score", "judge_language_ok"]].copy()
    extra["judge_score"] = pd.to_numeric(extra["judge_score"], errors="coerce")
    scored = scored.merge(extra, on="response_id", how="left")
    scored["version"] = scored["prompt_version"].str.replace("-live", "", regex=False)
    scored["combined_auto"] = 0.6 * scored["factuality_auto"] + 0.4 * scored["terminology_auto"]
    scored["flagged"] = scored["suggested_tags"] != ""
    for tag in ("wrong_language", "untranslated_text", "terminology_mismatch", "omission", "truncated",
                "wrong_number", "hallucination"):
        scored[f"tag_{tag}"] = scored["suggested_tags"].str.contains(tag)
    return scored


def version_summary(scored: pd.DataFrame) -> pd.DataFrame:
    g = scored.groupby("version").agg(
        answers=("response_id", "count"),
        judge_mean=("judge_score", "mean"),
        factuality_auto=("factuality_auto", "mean"),
        terminology_auto=("terminology_auto", "mean"),
        flagged_pct=("flagged", "mean"),
        terminology_mismatch_pct=("tag_terminology_mismatch", "mean"),
        omission_pct=("tag_omission", "mean"),
        wrong_language_pct=("tag_wrong_language", "mean"),
        untranslated_pct=("tag_untranslated_text", "mean"),
        truncated_pct=("tag_truncated", "mean"),
    ).reset_index()
    for col in [c for c in g.columns if c.endswith("_pct")]:
        g[col] = (100 * g[col]).round(0)
    return g.round(2)


def language_table(scored: pd.DataFrame, metric: str) -> pd.DataFrame:
    t = scored.pivot_table(index="language_name", columns="version", values=metric, aggfunc="mean")
    return t.round(2)


def bootstrap_ci(diffs: np.ndarray, n: int = 5000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    diffs = diffs[~np.isnan(diffs)]
    if len(diffs) == 0:
        return (float("nan"), float("nan"))
    means = rng.choice(diffs, size=(n, len(diffs)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired_comparisons(scored: pd.DataFrame, metric: str) -> pd.DataFrame:
    """For each pair of versions: mean difference on the same cases, 95% bootstrap CI, wins/losses/ties."""
    wide = scored.pivot_table(index="case_id", columns="version", values=metric, aggfunc="mean")
    rows = []
    for a, b in combinations(sorted(wide.columns), 2):
        d = (wide[b] - wide[a]).to_numpy(dtype=float)
        d = d[~np.isnan(d)]
        lo, hi = bootstrap_ci(d)
        rows.append({
            "comparison": f"{b} vs {a}",
            "cases": len(d),
            "mean_diff": round(float(d.mean()), 2) if len(d) else float("nan"),
            "ci_low": round(lo, 2), "ci_high": round(hi, 2),
            f"{b}_better": int((d > 0).sum()), f"{a}_better": int((d < 0).sum()), "ties": int((d == 0).sum()),
        })
    return pd.DataFrame(rows)


def _md_table(df: pd.DataFrame, index: bool = False) -> str:
    df = df.reset_index() if index else df
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines)


def write_report(scored: pd.DataFrame, model: str, judge_model: str | None, report_path: Path,
                 summary_path: Path) -> str:
    summary = version_summary(scored)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False)

    has_judge = scored["judge_score"].notna().any()
    parts = [
        "# Prompt versions on real model output",
        "",
        f"Generated {_now()[:10]} with `{model}` (temperature 0, one answer per case and version)"
        + (f", graded by `{judge_model}` as LLM judge." if has_judge else ", without the LLM judge."),
        f"{scored['case_id'].nunique()} cases ({scored['scenario'].nunique()} scenarios × "
        f"{scored['language'].nunique()} languages), {len(scored)} answers. Raw answers: `data/live_responses.csv`.",
        "",
        "## Overall",
        "",
        _md_table(summary),
        "",
        "`judge_mean` is the LLM judge's 1–5 factuality grade. `factuality_auto` and `terminology_auto` are the "
        "heuristic 0–100 scores from `src/scoring.py`. The `_pct` columns are the share of answers that received "
        "each suggested tag.",
        "",
    ]
    if has_judge:
        parts += ["## Judge score by language", "", _md_table(language_table(scored, "judge_score"), index=True), ""]
    parts += [
        "## Terminology score by language", "", _md_table(language_table(scored, "terminology_auto"), index=True), "",
        "## Paired differences (same cases)", "",
    ]
    metrics = (["judge_score"] if has_judge else []) + ["combined_auto"]
    for m in metrics:
        parts += [f"**{m}**", "", _md_table(paired_comparisons(scored, m)), ""]
    parts += [
        "A difference is only worth reporting when its 95% interval excludes zero.",
        "",
        "## Limits",
        "",
        "- One model, one answer per case at temperature 0, 36 cases. Small differences are within noise.",
        "- The judge is itself a language model and can share the generator's blind spots, especially when both "
        "are from the same model family.",
        "- The heuristic scores check key facts and glossary terms; they do not catch invented claims that contain "
        "no number.",
        "- The policies and questions are synthetic HR scenarios, so the results describe these prompts on this "
        "task, not prompt quality in general.",
        "",
    ]
    text = "\n".join(parts)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return text
