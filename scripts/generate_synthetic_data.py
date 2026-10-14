#!/usr/bin/env python3
"""Generate the demo datasets.

Review data
    data/cases.csv      one row per (scenario, language): question, policy context,
                        reference answer, key facts, required glossary concepts
    data/responses.csv  one row per (case, prompt version) with a synthetic response.
                        Errors are injected with a seeded RNG and recorded in
                        `injected_errors`, which is what makes the scorer's recall
                        measurable (see src/scoring.calibration).

Usage data
    data/warehouse_events.csv                 server-side product events (all channels)
    data/pendo_feature_events.csv             what a Pendo feature-events export of the
                                              web app would look like for the same period
    data/databricks_feature_usage_weekly.csv  sql/feature_usage_weekly.sql run over the
                                              warehouse events with DuckDB

Everything is deterministic for a given --seed. No real users, accounts or policies.

    python scripts/generate_synthetic_data.py --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data import Glossary, load_glossary  # noqa: E402
from src.scoring import fact_present  # noqa: E402
from src.sources import feature_usage_sql, run_sql_locally  # noqa: E402
from src.textnorm import extract_numbers, join_sentences, number_present, numeric_core, split_sentences  # noqa: E402

VERSIONS = ["v1", "v2", "v3"]

# Probability of 0 / 1 / 2 injected errors per response, by prompt version.
N_ERRORS_P = {"v1": [0.30, 0.45, 0.25], "v2": [0.62, 0.30, 0.08], "v3": [0.72, 0.24, 0.04]}

# Relative weight of each error type, by prompt version. The story: v2 adds the
# glossary and a grounding rule, so terminology and language errors drop; v3
# tightens number handling, so wrong numbers drop further but truncation is still common.
ERROR_WEIGHTS = {
    "v1": {"terminology_mismatch": 0.28, "omission": 0.18, "wrong_number": 0.14, "hallucination": 0.18,
           "untranslated_text": 0.08, "wrong_language": 0.07, "truncated": 0.07},
    "v2": {"terminology_mismatch": 0.08, "omission": 0.22, "wrong_number": 0.18, "hallucination": 0.22,
           "untranslated_text": 0.10, "wrong_language": 0.05, "truncated": 0.15},
    "v3": {"terminology_mismatch": 0.06, "omission": 0.22, "wrong_number": 0.10, "hallucination": 0.18,
           "untranslated_text": 0.14, "wrong_language": 0.03, "truncated": 0.27},
}

_NUM_BEFORE = r"(?<![\d.,])"
_NUM_AFTER = r"(?!\d)(?![.,]\d)"


# --------------------------------------------------------------------------- #
# Review data
# --------------------------------------------------------------------------- #

def load_seed() -> dict:
    with open(config.SEED_DIR / "scenarios.json", encoding="utf-8") as fh:
        return json.load(fh)


def compose(parts: list[str], lang: str) -> str:
    return join_sentences([p for p in parts if p], lang)


def perturb_number(core: str, allowed: set[str], rng: random.Random) -> str:
    """Return a different number in the same format, avoiding numbers that would be legitimate."""
    sep = "," if "," in core else "."
    if sep in core:
        value = float(core.replace(",", "."))
        options = []
        for delta in (0.25, 0.5, 0.75, 1.0, -0.25, -0.5):
            new = round(value + delta, 2)
            if new <= 0:
                continue
            text = f"{new:.2f}".rstrip("0").rstrip(".")
            if "." not in text:
                text += ".0"
            if f"{new:g}" not in allowed:
                options.append(text.replace(".", sep))
        return rng.choice(options) if options else core
    n = int(core)
    options = sorted({x for x in (n - 5, n - 2, n - 1, n + 1, n + 2, n + 5, n * 2)
                      if x > 0 and x != n and str(x) not in allowed})
    return str(rng.choice(options)) if options else core


def apply_terminology(body: str, lang: str, concepts: list[str], glossary: Glossary, rng: random.Random):
    candidates = []
    for concept in concepts:
        entry = glossary.entry(concept, lang)
        if entry is None or not entry.avoid:
            continue
        for variant in entry.preferred:
            m = re.search(re.escape(variant), body, flags=re.IGNORECASE)
            if m:
                candidates.append((m, entry.avoid[0]))
                break
    if not candidates:
        return body, False, None
    m, avoid = rng.choice(candidates)
    return body[: m.start()] + avoid + body[m.end():], True, avoid


def apply_wrong_number(body: str, key_facts: list[str], allowed: set[str], rng: random.Random):
    numeric = [(f, numeric_core(f)) for f in key_facts if numeric_core(f)]
    rng.shuffle(numeric)
    for fact, core in numeric:
        m = re.search(_NUM_BEFORE + re.escape(core) + _NUM_AFTER, body)
        if m:
            new = perturb_number(core, allowed, rng)
            if new == core:
                continue
            return body[: m.start()] + new + body[m.end():], True, fact, new
    return body, False, None, None


def apply_omission(body: str, lang: str, key_facts: list[str], skip_fact: str | None,
                   protect: str | None, rng: random.Random):
    sentences = split_sentences(body, lang)
    if len(sentences) < 2:
        return body, False, None
    candidates = []
    for fact in key_facts:
        if fact == skip_fact:
            continue
        for i, s in enumerate(sentences):
            if protect and protect in s:
                continue
            if fact_present(fact, s):
                candidates.append((fact, i))
                break
    if not candidates:
        return body, False, None
    fact, i = rng.choice(candidates)
    del sentences[i]
    return join_sentences(sentences, lang), True, fact


def truncate(text: str, lang: str, rng: random.Random) -> str:
    cut = int(len(text) * rng.uniform(0.55, 0.75))
    if lang != "ja":
        space = text.rfind(" ", 0, cut)
        if space > 20:
            cut = space
    return text[:cut].rstrip(" ,;:.!?。、")


def sample_errors(version: str, lang: str, rng: random.Random) -> list[str]:
    k = rng.choices([0, 1, 2], weights=N_ERRORS_P[version])[0]
    weights = dict(ERROR_WEIGHTS[version])
    if lang == "en":
        weights.pop("untranslated_text")
    chosen: list[str] = []
    pool = dict(weights)
    while len(chosen) < k and pool:
        pick = rng.choices(list(pool), weights=list(pool.values()))[0]
        chosen.append(pick)
        pool.pop(pick)
    if "wrong_language" in chosen:
        return ["wrong_language"]
    if "truncated" in chosen:
        # An English sentence appended at the end would be the first thing cut off.
        chosen = [e for e in chosen if e != "untranslated_text"]
    # Apply in a fixed order so the perturbations compose predictably.
    order = ["terminology_mismatch", "wrong_number", "omission", "hallucination", "untranslated_text", "truncated"]
    return [e for e in order if e in chosen]


def build_response(seed: dict, scenario: dict, lang: str, version: str, glossary: Glossary,
                   rng: random.Random) -> tuple[str, list[str]]:
    cell = scenario["cells"][lang]
    greeting = scenario.get("greeting", {}).get(lang) or rng.choice(seed["greetings"][lang])
    closing = rng.choice(seed["closings"][lang])
    body = cell["body"]
    key_facts = cell["key_facts"]
    allowed = set(extract_numbers(cell["reference"], lang)) | set(extract_numbers(cell["context"], lang))
    allowed |= set(extract_numbers(" ".join(key_facts), lang))

    applied: list[str] = []
    errors = sample_errors(version, lang, rng)

    if errors == ["wrong_language"]:
        other = "fr" if lang == "en" else "en"
        other_cell = scenario["cells"][other]
        other_greeting = scenario.get("greeting", {}).get(other) or rng.choice(seed["greetings"][other])
        text = compose([other_greeting, other_cell["body"], rng.choice(seed["closings"][other])], other)
        return text, ["wrong_language"]

    skip_fact, protect = None, None
    markers: dict[str, str] = {}  # error -> substring that must survive truncation for the label to hold
    if "terminology_mismatch" in errors:
        body, ok, marker = apply_terminology(body, lang, scenario["required_concepts"], glossary, rng)
        if ok:
            applied.append("terminology_mismatch")
            markers["terminology_mismatch"] = marker
    if "wrong_number" in errors:
        body, ok, skip_fact, protect = apply_wrong_number(body, key_facts, allowed, rng)
        if ok:
            applied.append("wrong_number")
            markers["wrong_number"] = protect
    if "omission" in errors:
        body, ok, _ = apply_omission(body, lang, key_facts, skip_fact, protect, rng)
        if ok:
            applied.append("omission")
    if "hallucination" in errors:
        sentence = rng.choice(seed["hallucinations"][lang])
        body = compose([body, sentence], lang)
        applied.append("hallucination")
        markers["hallucination"] = sentence[: max(12, len(sentence) // 2)]

    text = compose([greeting, body, closing], lang)
    if "untranslated_text" in errors:
        text = compose([text, rng.choice(seed["untranslated"])], lang)
        applied.append("untranslated_text")
    if "truncated" in errors:
        text = truncate(text, lang, rng)
        applied.append("truncated")
        # Labels only count if the injected text survived the cut.
        def survived(error: str) -> bool:
            if error not in markers:
                return True
            if error == "wrong_number":
                return number_present(markers[error], text)
            return markers[error] in text
        applied = [e for e in applied if survived(e)]
    return text, applied


def build_review_data(seed_value: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    seed = load_seed()
    glossary = load_glossary()
    rng = random.Random(seed_value)
    generated_at = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc).isoformat()

    cases, responses = [], []
    for scenario in seed["scenarios"]:
        for lang, cell in scenario["cells"].items():
            case_id = f"{scenario['id']}-{lang}"
            cases.append({
                "case_id": case_id,
                "scenario": scenario["id"],
                "scenario_title": scenario["title"],
                "language": lang,
                "language_name": seed["languages"][lang]["name"],
                "rtl": seed["languages"][lang]["rtl"],
                "question": cell["question"],
                "context": cell["context"],
                "reference_answer": cell["reference"],
                "key_facts": "|".join(cell["key_facts"]),
                "required_concepts": "|".join(scenario["required_concepts"]),
            })
            for version in VERSIONS:
                text, applied = build_response(seed, scenario, lang, version, glossary, rng)
                responses.append({
                    "response_id": f"{case_id}-{version}",
                    "case_id": case_id,
                    "prompt_version": version,
                    "source": "synthetic",
                    "response": text,
                    "injected_errors": "|".join(applied),
                    "generated_at": generated_at,
                })
    return pd.DataFrame(cases), pd.DataFrame(responses)


# --------------------------------------------------------------------------- #
# Usage data
# --------------------------------------------------------------------------- #

FEATURES = [
    # name, product_area, page, adoption (share of users who ever use it), p_daily (per adopter),
    # depth (mean events per use), mobile share, weekly trend multiplier
    ("Timesheet Submit",     "Time",      "/time/timesheet",      0.95, 0.090, 1.6, 0.35, 1.00),
    ("Pay Statement View",   "Pay",       "/pay/statements",      0.90, 0.075, 1.2, 0.45, 1.01),
    ("Time-Off Request",     "Time",      "/time/time-off",       0.70, 0.040, 1.5, 0.40, 1.00),
    ("Benefits Enrollment",  "Benefits",  "/benefits/enroll",     0.45, 0.012, 3.0, 0.10, 1.00),
    ("Schedule View",        "Time",      "/time/schedule",       0.80, 0.110, 2.5, 0.60, 0.99),
    ("Assistant Chat",       "Assistant", "/assistant",           0.40, 0.070, 4.0, 0.30, 1.08),
    ("Expense Report",       "Expenses",  "/expenses/reports",    0.40, 0.040, 2.4, 0.25, 0.95),
    ("Org Directory Search", "People",    "/people/directory",    0.65, 0.055, 1.3, 0.20, 1.00),
]

LOCALES = {
    "en-US": ("United States", 0.38), "en-CA": ("Canada", 0.12), "fr-CA": ("Canada", 0.12),
    "es-MX": ("Mexico", 0.08), "es-ES": ("Spain", 0.04), "de-DE": ("Germany", 0.09),
    "ja-JP": ("Japan", 0.07), "ar-SA": ("Saudi Arabia", 0.05), "pt-BR": ("Brazil", 0.05),
}
BROWSERS = (["Chrome", "Edge", "Safari", "Firefox"], [0.62, 0.18, 0.14, 0.06])


def build_usage_data(seed_value: int, end: date, weeks: int, n_accounts: int):
    rng = np.random.default_rng(seed_value)
    locale_names = list(LOCALES)
    locale_p = np.array([LOCALES[k][1] for k in locale_names])
    locale_p = locale_p / locale_p.sum()

    # Accounts and users
    sizes = np.clip(np.round(rng.lognormal(mean=2.4, sigma=0.7, size=n_accounts)), 3, 90).astype(int)
    accounts = []
    users = []
    for i, size in enumerate(sizes):
        acct = f"acct_{i + 1:03d}"
        tier = "Standard" if size < 10 else ("Pro" if size < 40 else "Enterprise")
        primary = rng.choice(locale_names, p=locale_p)
        accounts.append((acct, tier, primary))
        for _ in range(size):
            locale = primary if rng.random() < 0.8 else rng.choice(locale_names, p=locale_p)
            users.append({
                "user_id": f"u_{len(users) + 1:05d}",
                "account_id": acct,
                "plan_tier": tier,
                "locale": locale,
                "country": LOCALES[locale][0],
                "browser": rng.choice(BROWSERS[0], p=BROWSERS[1]),
                "activity": float(np.clip(rng.gamma(2.0, 0.5), 0.15, 3.0)),
                "mobile_pref": float(rng.beta(2, 5)),
                "pendo_blocked": bool(rng.random() < 0.04),
            })
    users_df = pd.DataFrame(users)
    n_users = len(users_df)

    days = [end - timedelta(days=d) for d in range(weeks * 7 - 1, -1, -1)]
    day_idx = np.arange(len(days))
    week_idx = day_idx // 7
    weekday = np.array([d.weekday() for d in days])
    weekday_factor = np.where(weekday < 5, 1.0, 0.12)

    activity = users_df["activity"].to_numpy()
    mobile_pref = users_df["mobile_pref"].to_numpy()

    rows = []
    for name, area, page, adoption, p_daily, depth, mobile_share, trend in FEATURES:
        trend_factor = trend ** week_idx
        seasonal = np.ones(len(days))
        if name == "Benefits Enrollment":  # ramp into enrollment season over the last two weeks
            seasonal[week_idx == weeks - 2] = 1.8
            seasonal[week_idx == weeks - 1] = 3.4
        if name == "Expense Report":       # month-end bump
            seasonal[[i for i, d in enumerate(days) if d.day >= 27 or d.day <= 2]] *= 1.6
        # Not everyone uses every feature: adopters are a fixed subset of users.
        adopter = (rng.random(n_users) < adoption).astype(float)
        p = np.clip(np.outer(activity * adopter, p_daily * weekday_factor * trend_factor * seasonal), 0, 0.95)
        used = rng.random(p.shape) < p
        user_ix, day_ix = np.nonzero(used)
        n_events = 1 + rng.poisson(max(depth - 1, 0.05), size=len(user_ix))
        p_mobile = np.clip(mobile_share * (0.5 + mobile_pref[user_ix]), 0.0, 0.95)
        for u, d, k, pm in zip(user_ix, day_ix, n_events, p_mobile):
            user = users_df.iloc[u]
            base = datetime.combine(days[d], datetime.min.time())
            for _ in range(int(k)):
                r = rng.random()
                if name == "Timesheet Submit" and r < 0.05:
                    channel = "api"
                elif r < 0.05 + pm:
                    channel = "mobile"
                else:
                    channel = "web"
                ts = base + timedelta(minutes=int(rng.integers(7 * 60, 19 * 60)))
                rows.append((ts, user["user_id"], user["account_id"], name, area, channel,
                             user["locale"], user["country"], user["plan_tier"], user["browser"],
                             page, bool(user["pendo_blocked"])))

    events = pd.DataFrame(rows, columns=[
        "event_ts", "user_id", "account_id", "feature_name", "product_area", "channel",
        "locale", "country", "plan_tier", "browser", "page", "pendo_blocked",
    ]).sort_values("event_ts").reset_index(drop=True)
    events.insert(0, "event_id", [f"evt_{i + 1:07d}" for i in range(len(events))])

    warehouse = events[["event_id", "event_ts", "user_id", "account_id", "feature_name",
                        "product_area", "channel", "locale", "country", "plan_tier"]].copy()

    # Pendo sees the web app only, and misses visitors whose browsers block the agent.
    web = events[(events["channel"] == "web") & (~events["pendo_blocked"])].copy()
    web["day"] = web["event_ts"].dt.date
    web["minutes"] = np.round(rng.exponential(1.4, size=len(web)) + 0.3, 1)
    pendo = (
        web.groupby(["user_id", "account_id", "feature_name", "page", "day", "browser", "country", "locale"])
        .agg(num_events=("event_id", "count"), num_minutes=("minutes", "sum"))
        .reset_index()
    )
    pendo["num_minutes"] = pendo["num_minutes"].round(1)
    pendo = pendo.rename(columns={
        "user_id": "Visitor ID", "account_id": "Account ID", "feature_name": "Feature", "page": "Page",
        "day": "Day", "num_events": "Number of Events", "num_minutes": "Number of Minutes",
        "browser": "Browser", "country": "Country", "locale": "Language",
    })
    pendo.insert(4, "App", "Employee Web")
    pendo = pendo[["Visitor ID", "Account ID", "Feature", "Page", "App", "Day", "Number of Events",
                   "Number of Minutes", "Browser", "Country", "Language"]].sort_values(["Day", "Visitor ID"])

    weekly = run_sql_locally(feature_usage_sql(), warehouse)
    return warehouse, pendo.reset_index(drop=True), weekly


# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--end-date", default="2026-10-11", help="last day of the usage window (YYYY-MM-DD)")
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--accounts", type=int, default=40)
    parser.add_argument("--out", default=str(config.DATA_DIR))
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cases, responses = build_review_data(args.seed)
    cases.to_csv(out / "cases.csv", index=False)
    responses.to_csv(out / "responses.csv", index=False)
    counts = responses["injected_errors"].str.split("|").explode().value_counts()
    print(f"cases: {len(cases)}  responses: {len(responses)}")
    print("injected errors:", {k: int(v) for k, v in counts.items() if k})

    end = date.fromisoformat(args.end_date)
    warehouse, pendo, weekly = build_usage_data(args.seed, end, args.weeks, args.accounts)
    warehouse.to_csv(out / "warehouse_events.csv", index=False)
    pendo.to_csv(out / "pendo_feature_events.csv", index=False)
    weekly.to_csv(out / "databricks_feature_usage_weekly.csv", index=False)
    print(f"warehouse events: {len(warehouse)}  pendo rows: {len(pendo)}  weekly rollup rows: {len(weekly)}")


if __name__ == "__main__":
    main()
