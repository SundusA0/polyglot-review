# Prompt versions on real model output

Generated 2026-10-14 with `gemini-flash-lite-latest` (temperature 0, one answer per case and version), graded by `gemini-flash-lite-latest` as LLM judge.
36 cases (6 scenarios × 6 languages), 108 answers. Raw answers: `data/live_responses.csv`.

## Overall

| version | answers | judge_mean | factuality_auto | terminology_auto | flagged_pct | terminology_mismatch_pct | omission_pct | wrong_language_pct | untranslated_pct | truncated_pct |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 | 36 | 4.61 | 86.72 | 78.75 | 39.0 | 8.0 | 28.0 | 0.0 | 0.0 | 3.0 |
| v2 | 36 | 4.81 | 97.22 | 97.22 | 3.0 | 0.0 | 0.0 | 0.0 | 0.0 | 3.0 |
| v3 | 36 | 4.58 | 94.03 | 97.22 | 17.0 | 0.0 | 14.0 | 0.0 | 0.0 | 3.0 |

`judge_mean` is the LLM judge's 1–5 factuality grade. `factuality_auto` and `terminology_auto` are the heuristic 0–100 scores from `src/scoring.py`. The `_pct` columns are the share of answers that received each suggested tag.

## Judge score by language

| language_name | v1 | v2 | v3 |
|---|---|---|---|
| Arabic | 4.0 | 4.17 | 4.17 |
| English | 4.83 | 4.83 | 4.67 |
| French | 4.83 | 5.0 | 4.67 |
| German | 4.83 | 5.0 | 5.0 |
| Japanese | 4.67 | 5.0 | 4.67 |
| Spanish | 4.5 | 4.83 | 4.33 |

## Terminology score by language

| language_name | v1 | v2 | v3 |
|---|---|---|---|
| Arabic | 69.5 | 83.33 | 83.33 |
| English | 94.5 | 100.0 | 100.0 |
| French | 94.5 | 100.0 | 100.0 |
| German | 52.83 | 100.0 | 100.0 |
| Japanese | 75.0 | 100.0 | 100.0 |
| Spanish | 86.17 | 100.0 | 100.0 |

## Paired differences (same cases)

**judge_score**

| comparison | cases | mean_diff | ci_low | ci_high | v2_better | v1_better | ties | v3_better |
|---|---|---|---|---|---|---|---|---|
| v2 vs v1 | 36 | 0.19 | 0.0 | 0.39 | 9.0 | 3.0 | 24 |  |
| v3 vs v1 | 36 | -0.03 | -0.28 | 0.22 |  | 9.0 | 20 | 7.0 |
| v3 vs v2 | 36 | -0.22 | -0.39 | -0.06 | 10.0 |  | 24 | 2.0 |

**combined_auto**

| comparison | cases | mean_diff | ci_low | ci_high | v2_better | v1_better | ties | v3_better |
|---|---|---|---|---|---|---|---|---|
| v2 vs v1 | 36 | 13.69 | 7.11 | 21.16 | 13.0 | 0.0 | 23 |  |
| v3 vs v1 | 36 | 11.77 | 5.14 | 19.37 |  | 2.0 | 21 | 13.0 |
| v3 vs v2 | 36 | -1.92 | -3.58 | -0.42 | 5.0 |  | 31 | 0.0 |

A difference is only worth reporting when its 95% interval excludes zero.

## Limits

- One model, one answer per case at temperature 0, 36 cases. Small differences are within noise.
- The judge is itself a language model and can share the generator's blind spots, especially when both are from the same model family.
- The heuristic scores check key facts and glossary terms; they do not catch invented claims that contain no number.
- The policies and questions are synthetic HR scenarios, so the results describe these prompts on this task, not prompt quality in general.
