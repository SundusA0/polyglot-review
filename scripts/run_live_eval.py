#!/usr/bin/env python3
"""Run every case through a real model with each prompt version, judge the answers,
score them, and write a report.

    python scripts/run_live_eval.py                      # all 36 cases × v1, v2, v3 with the LLM judge
    python scripts/run_live_eval.py --languages ar en    # a subset
    python scripts/run_live_eval.py --report-only        # rebuild the report from saved answers
    python scripts/run_live_eval.py --list-models        # show the model names your key can use

Works with OpenAI (OPENAI_API_KEY) or Google Gemini's free tier (GEMINI_API_KEY),
set in .env. Answers are saved to data/live_responses.csv after every call, so an
interrupted run resumes where it stopped. The report goes to docs/live_eval.md
and docs/live_eval_summary.csv, and the answers show up in the app as versions
"v1-live", "v2-live", "v3-live".
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from src import config  # noqa: E402
from src.data import load_cases, load_glossary  # noqa: E402
from src.live_eval import load_existing, run_generation, score_live, write_report  # noqa: E402
from src.llm import make_client, provider, resolve_api_key, resolve_model  # noqa: E402


def main() -> None:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default=None, help="generation model (default: GEMINI_MODEL / OPENAI_MODEL)")
    p.add_argument("--judge-model", default=None, help="judge model (default: same as --model)")
    p.add_argument("--versions", nargs="+", default=["v1", "v2", "v3"])
    p.add_argument("--languages", nargs="+", default=None, help="e.g. ar en (default: all)")
    p.add_argument("--no-judge", action="store_true", help="skip the LLM judge (half the API calls)")
    p.add_argument("--delay", type=float, default=None,
                   help="seconds between calls (default: 6 for Gemini's free tier, 0 for OpenAI)")
    p.add_argument("--report-only", action="store_true", help="do not call the API; rebuild the report")
    p.add_argument("--list-models", action="store_true", help="print the models available to your key")
    args = p.parse_args()

    prov = provider()
    cases = load_cases()
    if args.languages:
        cases = cases[cases["language"].isin(args.languages)]
    glossary = load_glossary()
    model = resolve_model(args.model)
    judge_model = args.judge_model or model

    if args.list_models:
        client = make_client(resolve_api_key())
        for m in sorted(client.models.list(), key=lambda m: m.id):
            print(m.id)
        return

    if args.report_only:
        live = load_existing(config.LIVE_RESPONSES_CSV)
        if live.empty:
            sys.exit("No saved answers in data/live_responses.csv yet. Run without --report-only first.")
    else:
        key = resolve_api_key()
        if not key:
            sys.exit("No API key found. Add GEMINI_API_KEY (free) or OPENAI_API_KEY to .env.")
        delay = args.delay if args.delay is not None else (6.0 if prov == "gemini" else 0.0)
        n_calls = len(cases) * len(args.versions) * (1 if args.no_judge else 2)
        print(f"Provider: {prov} · model: {model} · judge: {'off' if args.no_judge else judge_model}")
        print(f"About {n_calls} API calls" + (f", {delay:.0f}s apart (about {n_calls * delay / 60:.0f} min)"
                                               if delay else ""))
        try:
            live = run_generation(cases, args.versions, make_client(key), model, glossary,
                                  config.LIVE_RESPONSES_CSV, judge=not args.no_judge, judge_model=judge_model,
                                  delay=delay, provider=prov)
        except KeyboardInterrupt:
            sys.exit("\nStopped. Answers so far are saved; run the same command again to continue.")
        except Exception as exc:
            sys.exit(f"\nStopped by an API error: {exc}\n\nAnswers so far are saved in data/live_responses.csv. "
                     "If this is a daily quota limit, run the same command again tomorrow (or later) to continue.")

    live = live[live["case_id"].isin(cases["case_id"])]
    # Describe the models that actually produced the saved answers.
    model = ", ".join(sorted(s.split(":", 1)[-1] for s in live["source"].unique() if s)) or model
    judged = sorted(m for m in live["judge_model"].unique() if m)
    scored = score_live(live, cases, glossary)
    report = write_report(scored, model, ", ".join(judged) or None,
                          config.LIVE_REPORT_MD, config.LIVE_SUMMARY_CSV)
    print("\n" + report)
    print(f"Saved {config.LIVE_REPORT_MD.relative_to(ROOT)} and {config.LIVE_SUMMARY_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
