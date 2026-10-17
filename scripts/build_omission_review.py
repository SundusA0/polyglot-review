#!/usr/bin/env python3
"""Regenerate an initial, UNVERIFIED manual-review worksheet from actual Gemini traces.
Do not overwrite a completed human review; delete the existing file deliberately
only if you intend to regenerate the worksheet from the current source data.
"""
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402
from src.data import load_cases, load_glossary  # noqa: E402
from src.scoring import score_response  # noqa: E402

OUT = ROOT / 'docs' / 'omission_review.md'
if OUT.exists():
    print(f'{OUT.relative_to(ROOT)} already exists; not overwriting potential reviewer edits.')
    sys.exit(0)

cases = load_cases().set_index('case_id')
responses = pd.read_csv(config.LIVE_RESPONSES_CSV, dtype=str).fillna('')
lookup = {(row.case_id, row.prompt_version): row for row in responses.itertuples()}
glossary = load_glossary()

# Editorial hypotheses are deliberately *not* recorded as verified human labels.
# A reviewer must make their own judgment about what the question actually asks.
triage = {
    'pto_accrual-en': 'Supplemental annual total; the question asks about monthly accrual and carryover.',
    'pto_accrual-es': 'Supplemental annual total; the question asks about monthly accrual and carryover.',
    'pto_accrual-de': 'Supplemental annual total; the question asks about monthly accrual and carryover.',
    'pay_schedule-fr': 'Paper-cheque delay may matter for employees using cheques; user did not specify payment method.',
    'pay_schedule-es': 'Paper-cheque delay may matter for employees using cheques; user did not specify payment method.',
}
rows = []
v2_flagged = []
for cid, case in cases.iterrows():
    a, b = lookup.get((cid, 'v2-live')), lookup.get((cid, 'v3-live'))
    if a is None or b is None:
        raise SystemExit(f'Missing real model pair: {cid}')
    score2 = score_response(case.to_dict(), a.response, glossary)
    score3 = score_response(case.to_dict(), b.response, glossary)
    if 'omission' in score2.suggested_tags:
        v2_flagged.append(cid)
    if 'omission' in score3.suggested_tags:
        rows.append((cid, case, a, b, score3))

if len(rows) != 5 or v2_flagged:
    raise SystemExit(f'Unexpected flags: v3={len(rows)} v2={v2_flagged}; review the new results manually.')

parts = [
    '# Review of five automatically flagged omissions',
    '',
    '> **Status: human review pending.** These are factual-coverage alerts from the',
    '> deterministic scorer, **not** five confirmed failures to answer the user.',
    '> Preliminary triage notes below are editorial hypotheses, not validated reviewer labels.',
    '',
    '## Evaluation protocol',
    '',
    '- 36 fictional HR questions across six languages; 36 model answers for each prompt version.',
    '- The heuristic flags a response if its text is missing a reference key fact; that alone does not establish that the user needed the fact.',
    '- Review question and policy first. Assign **relevance** as `essential`, `conditional`, `supplementary`, or `not relevant`.',
    '- Assign **severity** as `high` (would likely mislead or materially impair user), `medium` (could matter in common contexts), `low` (minor useful detail), or `none` (answer meets question).',
    '- Record a brief evidence-based rationale, reviewer, and review date. Do not equate an LLM judge score with a complete human quality evaluation.',
    '',
    '## Triage overview',
    '',
    '| Case | Missing reference fact(s) | v2 judge | v3 judge | Preliminary interpretation | Human relevance | Human severity |',
    '| --- | --- | ---: | ---: | --- | --- | --- |',
]
for cid, case, a, b, score in rows:
    missing = ', '.join(score.factuality.facts_missing)
    parts.append(f'| [`{cid}`](#case-{cid}) | {missing} | {a.judge_score}/5 | {b.judge_score}/5 | {triage.get(cid,"Review needed")} | Pending | Pending |')
parts += [
    '',
    '## Detailed source evidence',
    '',
    'Exact texts below come from [`data/live_responses.csv`](../data/live_responses.csv) and',
    '[`data/cases.csv`](../data/cases.csv). Generated from immutable source rows; no fabricated judge remarks.',
    '',
]
for i, (cid, case, a, b, score) in enumerate(rows, start=1):
    parts += [
        f'<a id="case-{cid}"></a>',
        f'### {i}. `{cid}`',
        '',
        '**User question**', '', f'> {case["question"]}', '',
        '**Fictional policy context**', '', f'> {case["context"]}', '',
        '**v2 — glossary-grounded output (verbatim)**', '', f'> {a.response.replace(chr(10), chr(10) + "> ")}', '',
        f'**v2 judge: {a.judge_score}/5**', '', f'> {a.judge_rationale}', '',
        '**v3 — stricter output (verbatim)**', '', f'> {b.response.replace(chr(10), chr(10) + "> ")}', '',
        f'**v3 judge: {b.judge_score}/5**', '', f'> {b.judge_rationale}', '',
        '**Deterministic checker — missing reference facts:** ' + ', '.join(f'`{fact}`' for fact in score.factuality.facts_missing),
        '',
        '**Preliminary triage (not validated):** ' + triage.get(cid, 'No preliminary assessment.'),
        '',
        '**Human review:**',
        '- Relevance (`essential` / `conditional` / `supplementary` / `not relevant`): **Pending**',
        '- Severity (`high` / `medium` / `low` / `none`): **Pending**',
        '- Required to answer this specific question? **Pending**',
        '- Rationale and alternative interpretations: **Pending**',
        '- Reviewer / date: **Pending**',
        '', '---', '',
    ]
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text('\n'.join(parts).rstrip() + '\n', encoding='utf-8')
print(f'Created {OUT.relative_to(ROOT)} with {len(rows)} cases (human ratings pending).')
