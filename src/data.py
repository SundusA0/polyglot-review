"""Loading cases, responses, the glossary and prompt templates."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import CASES_CSV, GLOSSARY_CSV, PROMPTS_DIR, RESPONSES_CSV

SEP = "|"


def split_list(value) -> list[str]:
    """Pipe-separated CSV cells -> list (empty/NaN -> [])."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    return [part.strip() for part in text.split(SEP) if part.strip()]


@dataclass
class GlossaryEntry:
    concept: str
    language: str
    preferred: list[str]
    avoid: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def canonical(self) -> str:
        return self.preferred[0] if self.preferred else self.concept


class Glossary:
    """Preferred / discouraged terminology per concept and language."""

    def __init__(self, df: pd.DataFrame):
        self._entries: dict[tuple[str, str], GlossaryEntry] = {}
        for row in df.itertuples(index=False):
            entry = GlossaryEntry(
                concept=str(row.concept).strip(),
                language=str(row.language).strip(),
                preferred=split_list(row.preferred),
                avoid=split_list(row.avoid),
                note="" if pd.isna(row.note) else str(row.note),
            )
            self._entries[(entry.concept, entry.language)] = entry
        self.df = df

    @classmethod
    def from_csv(cls, path: Path = GLOSSARY_CSV) -> "Glossary":
        return cls(pd.read_csv(path))

    def entry(self, concept: str, language: str) -> GlossaryEntry | None:
        return self._entries.get((concept, language))

    def concepts(self) -> list[str]:
        return sorted({c for c, _ in self._entries})

    def languages(self) -> list[str]:
        return sorted({lang for _, lang in self._entries})

    def for_language(self, language: str) -> list[GlossaryEntry]:
        return [e for (c, lang), e in self._entries.items() if lang == language]

    def prompt_block(self, language: str, concepts: list[str] | None = None) -> str:
        """Render the glossary as a bullet list for a prompt template."""
        entries = self.for_language(language)
        if concepts:
            entries = [e for e in entries if e.concept in concepts]
        lines = []
        for e in sorted(entries, key=lambda x: x.concept):
            line = f"- {e.concept.replace('_', ' ')}: use \"{e.canonical}\""
            if e.avoid:
                line += " (not: " + ", ".join(f'"{a}"' for a in e.avoid) + ")"
            lines.append(line)
        return "\n".join(lines) if lines else "- (no glossary entries for this language)"


def load_cases(path: Path = CASES_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    df["key_facts_list"] = df["key_facts"].map(split_list)
    df["required_concepts_list"] = df["required_concepts"].map(split_list)
    df["rtl"] = df["rtl"].astype(str).str.lower().isin(["true", "1", "yes"])
    return df


def load_responses(path: Path = RESPONSES_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    return df


def load_glossary(path: Path = GLOSSARY_CSV) -> Glossary:
    return Glossary.from_csv(path)


def load_prompt_versions(prompts_dir: Path = PROMPTS_DIR) -> list[dict]:
    with open(prompts_dir / "versions.json", encoding="utf-8") as fh:
        return json.load(fh)


def load_prompt_template(version: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    for item in load_prompt_versions(prompts_dir):
        if item["version"] == version:
            return (prompts_dir / item["file"]).read_text(encoding="utf-8")
    raise KeyError(f"Unknown prompt version: {version}")


def render_template(template: str, **fields: str) -> str:
    """Replace {placeholders} for the given fields only, leaving other braces alone."""
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def case_record(cases: pd.DataFrame, case_id: str) -> dict:
    row = cases.loc[cases["case_id"] == case_id]
    if row.empty:
        raise KeyError(case_id)
    return row.iloc[0].to_dict()
