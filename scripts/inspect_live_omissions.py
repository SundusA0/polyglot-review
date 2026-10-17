#!/usr/bin/env python3
"""Print v2/v3 examples flagged for missing facts, for manual scientific review."""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402
from src.data import load_cases, load_glossary  # noqa: E402
from src.scoring import score_response  # noqa: E402

cases = load_cases().set_index("case_id")
glossary = load_glossary()
responses = pd.read_csv(config.LIVE_RESPONSES_CSV, dtype=str).fillna("")
lookup = {(r.case_id, r.prompt_version): r for r in responses.itertuples()}
parts = [
    "# Candidate omissions from real model output",
    "",
    "**These are automatic flags, not manually verified omissions.** For each case,",
    "check the user's question and policy context to decide whether the missing",
    "fact was required. Record independent decisions before claiming manual confirmation.",
    "",
]
count = 0
for cid, case in cases.iterrows():
    v2, v3 = lookup.get((cid, "v2-live")), lookup.get((cid, "v3-live"))
    if not v2 or not v3:
        continue
    checked = score_response(case.to_dict(), v3.response, glossary)
    # Restrict to actual omission tags; a blocked/empty answer may have
    # missing facts but is categorized separately by the scorer.
    if "omission" not in checked.suggested_tags:
        continue
    count += 1
    parts += [
        f"## {count}. {cid}", "", "**Question:**", "", case["question"], "",
        "**Policy context:**", "", case["context"], "",
        "**v2 glossary-grounded answer:**", "", v2.response, "",
        "**v3 stricter answer:**", "", v3.response, "",
        "**Automatically flagged missing facts (v3):**", "",
    ]
    parts += [f"- {fact}" for fact in checked.factuality.facts_missing]
    parts += ["", "**Human review:** Pending. Was each missing fact actually required to answer the question?", "", "---", ""]

out = ROOT / "docs" / "omission_candidates.md"
out.write_text("\n".join(parts), encoding="utf-8")
print(f"Saved {out.relative_to(ROOT)}: {count} cases flagged for manual review")
