"""Paths and constants shared across the app, the scripts and the tests."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
PROMPTS_DIR = ROOT / "prompts"
SQL_DIR = ROOT / "sql"
ANNOTATIONS_DIR = ROOT / "annotations"

CASES_CSV = DATA_DIR / "cases.csv"
RESPONSES_CSV = DATA_DIR / "responses.csv"
LIVE_RESPONSES_CSV = DATA_DIR / "live_responses.csv"
LIVE_REPORT_MD = ROOT / "docs" / "live_eval.md"
LIVE_SUMMARY_CSV = ROOT / "docs" / "live_eval_summary.csv"
GLOSSARY_CSV = DATA_DIR / "glossary.csv"
PENDO_CSV = DATA_DIR / "pendo_feature_events.csv"
WAREHOUSE_CSV = DATA_DIR / "warehouse_events.csv"
DATABRICKS_CSV = DATA_DIR / "databricks_feature_usage_weekly.csv"
FEATURE_USAGE_SQL = SQL_DIR / "feature_usage_weekly.sql"
ANNOTATIONS_CSV = ANNOTATIONS_DIR / "annotations.csv"
PREFERENCES_CSV = ANNOTATIONS_DIR / "preferences.csv"

# Error taxonomy used by reviewers. The first six can be suggested automatically;
# the rest are human-only.
ERROR_TAGS = [
    "omission",
    "wrong_number",
    "terminology_mismatch",
    "wrong_language",
    "untranslated_text",
    "truncated",
    "hallucination",
    "formatting",
    "tone",
    "other",
]
AUTO_TAGS = ERROR_TAGS[:6]

# Languages that use a decimal comma. Everything else is treated as decimal point.
DECIMAL_COMMA_LANGUAGES = {"fr", "es", "de", "pt", "it", "nl"}

# Map Pendo feature names to warehouse feature names when they differ.
# Left empty because the demo data uses identical names on both sides.
FEATURE_NAME_MAP: dict[str, str] = {}

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
