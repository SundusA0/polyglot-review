"""Heuristic scoring of a single response against its case.

Three signals are computed without any model call:

* factuality  - coverage of the case's key facts plus a check for numbers that
                appear in the response but nowhere in the policy context or
                reference ("numeric conflicts").
* terminology - whether the glossary's preferred term for each required concept
                is used, and whether any discouraged term slipped in.
* language    - a script/stopword heuristic that flags answers in the wrong
                language or with an English passage left untranslated.

From these the scorer suggests error tags for the reviewer. The suggestions are
starting points, not verdicts: they are pre-filled in the annotation form and the
reviewer edits them. Hallucinated claims that contain no number are invisible to
these heuristics; that is what the optional LLM judge and the human are for.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import pandas as pd
from rapidfuzz import fuzz

from .config import AUTO_TAGS
from .data import Glossary, split_list
from .textnorm import (
    detect_language,
    extract_numbers,
    has_english_passage,
    is_truncated,
    normalize,
    number_present,
    numeric_core,
)

FUZZY_THRESHOLD = 90
MIN_FUZZY_LEN = 8


# --------------------------------------------------------------------------- #
# Result containers
# --------------------------------------------------------------------------- #

@dataclass
class FactualityResult:
    score: int
    coverage: float
    facts_found: list[str] = field(default_factory=list)
    facts_missing: list[str] = field(default_factory=list)
    numeric_conflicts: list[str] = field(default_factory=list)


@dataclass
class TerminologyResult:
    score: int
    required: list[str] = field(default_factory=list)
    found: dict[str, str] = field(default_factory=dict)      # concept -> variant used
    missing: list[str] = field(default_factory=list)
    avoid_hits: list[tuple[str, str]] = field(default_factory=list)  # (concept, term)


@dataclass
class LanguageResult:
    expected: str
    detected: str | None
    confidence: float
    english_passage: bool

    @property
    def ok(self) -> bool:
        return self.detected is None or self.detected == self.expected


@dataclass
class ReviewScores:
    factuality: FactualityResult
    terminology: TerminologyResult
    language: LanguageResult
    truncated: bool
    suggested_tags: list[str]

    def as_flat_dict(self) -> dict:
        """One-level dict for tables and CSV export."""
        return {
            "factuality_auto": self.factuality.score,
            "fact_coverage": round(self.factuality.coverage, 3),
            "facts_missing": "|".join(self.factuality.facts_missing),
            "numeric_conflicts": "|".join(self.factuality.numeric_conflicts),
            "terminology_auto": self.terminology.score,
            "terms_missing": "|".join(self.terminology.missing),
            "avoid_term_hits": "|".join(t for _, t in self.terminology.avoid_hits),
            "language_detected": self.language.detected or "",
            "language_ok": self.language.ok,
            "english_passage": self.language.english_passage,
            "truncated": self.truncated,
            "suggested_tags": "|".join(self.suggested_tags),
        }


# --------------------------------------------------------------------------- #
# Matching helpers
# --------------------------------------------------------------------------- #

def _is_latin(text: str) -> bool:
    return all(ch.isascii() or "À" <= ch <= "ɏ" for ch in text if ch.isalpha())


def phrase_present(phrase: str, text: str, allow_fuzzy: bool = True, strict: bool = False) -> bool:
    """Accent/case-insensitive match with a fuzzy fallback for longer phrases.

    Latin-script terms must start at a word boundary so "OT" cannot match inside
    "other". Unless `strict`, terms of five or more characters may continue into
    a longer word, which keeps German compounds ("Überstundenvergütung") matching
    "Überstunden". Discouraged terms are checked strictly, otherwise "heures sup"
    would fire on "heures supplémentaires". Arabic and Japanese terms use plain
    substring matching: Arabic attaches prefixes to words and Japanese has no
    word boundaries.
    """
    p, t = normalize(phrase), normalize(text)
    if not p or not t:
        return False
    if _is_latin(p):
        tail = r"(?!\w)" if (strict or len(p) < 5) else ""
        if re.search(r"(?<!\w)" + re.escape(p) + tail, t):
            return True
    elif p in t:
        return True
    if allow_fuzzy and len(p) >= MIN_FUZZY_LEN:
        return fuzz.partial_ratio(p, t) >= FUZZY_THRESHOLD
    return False


def fact_present(fact: str, text: str) -> bool:
    core = numeric_core(fact)
    if core is not None:
        return number_present(core, text)
    return phrase_present(fact, text)


def first_variant_present(variants: list[str], text: str) -> str | None:
    for v in variants:
        if phrase_present(v, text, allow_fuzzy=len(normalize(v)) >= MIN_FUZZY_LEN):
            return v
    return None


# --------------------------------------------------------------------------- #
# Scorers
# --------------------------------------------------------------------------- #

def score_factuality(case: dict, response: str) -> FactualityResult:
    language = case["language"]
    facts = case.get("key_facts_list") or split_list(case.get("key_facts", ""))
    found = [f for f in facts if fact_present(f, response)]
    missing = [f for f in facts if f not in found]
    coverage = len(found) / len(facts) if facts else 1.0

    allowed = set(extract_numbers(case.get("reference_answer", ""), language))
    allowed |= set(extract_numbers(case.get("context", ""), language))
    allowed |= set(extract_numbers(case.get("key_facts", ""), language))
    conflicts = sorted({n for n in extract_numbers(response, language) if n not in allowed})

    score = max(0, min(100, round(100 * coverage) - 15 * len(conflicts)))
    return FactualityResult(score, coverage, found, missing, conflicts)


def score_terminology(case: dict, response: str, glossary: Glossary) -> TerminologyResult:
    language = case["language"]
    required = case.get("required_concepts_list") or split_list(case.get("required_concepts", ""))
    found: dict[str, str] = {}
    missing: list[str] = []
    avoid_hits: list[tuple[str, str]] = []
    for concept in required:
        entry = glossary.entry(concept, language)
        if entry is None:
            continue
        variant = first_variant_present(entry.preferred, response)
        if variant:
            found[concept] = variant
        else:
            missing.append(concept)
        for term in entry.avoid:
            if phrase_present(term, response, allow_fuzzy=False, strict=True):
                avoid_hits.append((concept, term))
    if required:
        score = round(100 * len(found) / len(required)) - 15 * len(avoid_hits)
    else:
        score = 100
    return TerminologyResult(max(0, min(100, score)), required, found, missing, avoid_hits)


def check_language(case: dict, response: str) -> LanguageResult:
    expected = case["language"]
    detected, confidence, _ = detect_language(response)
    english = has_english_passage(response, expected)
    if english and expected not in ("ja", "ar"):
        # Both languages are clearly present: the answer is in the right language
        # with an untranslated passage, even if English words happen to outnumber it.
        detected = expected
    return LanguageResult(expected, detected, confidence, english)


def _same_magnitude(a: str, b: str) -> bool:
    try:
        x, y = float(a.replace(",", ".")), float(b.replace(",", "."))
    except ValueError:
        return False
    if x <= 0 or y <= 0:
        return False
    return 0.2 <= x / y <= 5.0


def suggest_tags(fact: FactualityResult, term: TerminologyResult, lang: LanguageResult, truncated: bool,
                 glossary: Glossary | None = None, language: str = "") -> list[str]:
    """Turn the three signals into reviewer-facing tags.

    The rules try to name the *cause* once rather than every symptom: a cut-off
    answer is "truncated" (not also "omission" for the facts that fell off the
    end), a replaced glossary term is "terminology_mismatch" (not also "omission"
    when that term happened to be a key fact), and a missing preferred term only
    counts as a terminology problem when the surrounding content is present.
    """
    tags: list[str] = []
    if not lang.ok:
        # Everything else is noise when the answer is in the wrong language.
        return ["wrong_language"]

    # Key facts that are themselves the preferred wording of a concept whose
    # discouraged term was used: those are terminology problems, not omissions.
    replaced_terms: set[str] = set()
    if glossary is not None:
        for concept, _ in term.avoid_hits:
            entry = glossary.entry(concept, language)
            if entry:
                replaced_terms.update(normalize(v) for v in entry.preferred)
    missing = [f for f in fact.facts_missing if normalize(f) not in replaced_terms]
    missing_numeric = [f for f in missing if numeric_core(f) is not None]
    missing_other = [f for f in missing if numeric_core(f) is None]

    # Pair each unexpected number with a missing numeric fact of similar size:
    # "15 days" turning into "12 days" is a substitution, an unexplained "2019"
    # next to a missing "$25" is an invented figure plus an omission.
    substituted: set[str] = set()
    explained_conflicts: set[str] = set()
    for f in missing_numeric:
        for c in fact.numeric_conflicts:
            if _same_magnitude(numeric_core(f) or "", c):
                substituted.add(f)
                explained_conflicts.add(c)
    unexplained_conflicts = [c for c in fact.numeric_conflicts if c not in explained_conflicts]
    omitted_numeric = [f for f in missing_numeric if f not in substituted]

    if substituted:
        tags.append("wrong_number")
    if not truncated and (missing_other or omitted_numeric):
        tags.append("omission")
    if unexplained_conflicts:
        # A number nobody asked for: probably an invented date or figure.
        tags.append("hallucination")
    if term.avoid_hits or (term.missing and not fact.facts_missing and not truncated):
        tags.append("terminology_mismatch")
    if lang.english_passage:
        tags.append("untranslated_text")
    if truncated:
        tags.append("truncated")
    return tags


def score_response(case: dict, response: str, glossary: Glossary) -> ReviewScores:
    fact = score_factuality(case, response)
    term = score_terminology(case, response, glossary)
    lang = check_language(case, response)
    truncated = is_truncated(response)
    tags = suggest_tags(fact, term, lang, truncated, glossary, case["language"])
    return ReviewScores(fact, term, lang, truncated, tags)


def score_table(responses: pd.DataFrame, cases: pd.DataFrame, glossary: Glossary) -> pd.DataFrame:
    """Score every response row; returns responses joined with case fields and flat scores."""
    case_lookup = {row["case_id"]: row for row in cases.to_dict("records")}
    rows = []
    for rec in responses.to_dict("records"):
        case = case_lookup.get(rec["case_id"])
        if case is None:
            continue
        scores = score_response(case, rec["response"], glossary)
        rows.append({
            **rec,
            "scenario": case["scenario"],
            "language": case["language"],
            "language_name": case["language_name"],
            **scores.as_flat_dict(),
        })
    return pd.DataFrame(rows)


def calibration(scored: pd.DataFrame) -> pd.DataFrame:
    """Recall of each auto tag against the generator's injected-error labels.

    Only meaningful for synthetic rows (they carry `injected_errors`).
    Precision is reported too, but note that the heuristics sometimes flag a
    *real* consequence of another injected error (an omitted sentence can also
    remove a required term), which counts against precision here.
    """
    if "injected_errors" not in scored.columns:
        return pd.DataFrame()
    df = scored[scored["source"] == "synthetic"].copy()
    df["_injected"] = df["injected_errors"].map(split_list)
    df["_suggested"] = df["suggested_tags"].map(split_list)
    rows = []
    # hallucination is included to show its partial recall: only invented numbers are caught.
    for tag in AUTO_TAGS + ["hallucination"]:
        actual = df["_injected"].map(lambda xs: tag in xs)
        predicted = df["_suggested"].map(lambda xs: tag in xs)
        tp = int((actual & predicted).sum())
        fn = int((actual & ~predicted).sum())
        fp = int((~actual & predicted).sum())
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        rows.append({"tag": tag, "injected": tp + fn, "detected": tp, "false_alarms": fp,
                     "recall": recall, "precision": precision})
    return pd.DataFrame(rows)


def clean_false_positive_rate(scored: pd.DataFrame) -> float:
    """Share of synthetic responses with no injected error that still got a suggested tag."""
    if "injected_errors" not in scored.columns:
        return float("nan")
    clean = scored[(scored["source"] == "synthetic") & (scored["injected_errors"] == "")]
    if clean.empty:
        return float("nan")
    return float((clean["suggested_tags"] != "").mean())


def scores_to_dict(scores: ReviewScores) -> dict:
    return asdict(scores)
