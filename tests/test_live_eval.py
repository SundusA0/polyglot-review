"""The live evaluation pipeline, run against a fake OpenAI client (no network, no key)."""
import json
from types import SimpleNamespace

import numpy as np

from src.data import load_cases, load_glossary
from src.live_eval import bootstrap_ci, paired_comparisons, run_generation, score_live, write_report


class FakeClient:
    """Answers with the case's reference answer; v1 drops the last sentence. The judge always gives 4."""

    def __init__(self, cases):
        self.by_question = {c["question"]: c for c in cases.to_dict("records")}
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, temperature=None, response_format=None):
        self.calls += 1
        system, user = messages[0]["content"], messages[1]["content"]
        if response_format:  # judge call
            score = 4
            content = json.dumps({"score": score, "rationale": "ok", "unsupported_claims": [],
                                  "missing_facts": [], "language_ok": True})
        else:
            case = self.by_question[user]
            text = case["reference_answer"]
            if "Ground every statement" not in system:  # v1 template
                parts = text.split(". ")
                text = ". ".join(parts[:-1]) + "." if len(parts) > 1 else text
            content = text
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_generation_is_resumable_and_scores(tmp_path):
    cases = load_cases()
    cases = cases[cases["language"].isin(["en", "ar"])]
    glossary = load_glossary()
    out = tmp_path / "live.csv"
    client = FakeClient(cases)

    live = run_generation(cases, ["v1", "v2"], client, "fake-model", glossary, out, judge=True,
                          log=lambda m: None, sleep=lambda s: None)
    assert len(live) == len(cases) * 2
    assert client.calls == len(cases) * 2 * 2
    assert set(live["prompt_version"]) == {"v1-live", "v2-live"}

    # A second run makes no new calls.
    calls_before = client.calls
    run_generation(cases, ["v1", "v2"], client, "fake-model", glossary, out, judge=True,
                   log=lambda m: None, sleep=lambda s: None)
    assert client.calls == calls_before

    scored = score_live(live, cases, glossary)
    by_version = scored.groupby("version")["factuality_auto"].mean()
    assert by_version["v2"] == 100
    assert by_version["v1"] < by_version["v2"]

    report = write_report(scored, "fake-model", "fake-model", tmp_path / "r.md", tmp_path / "s.csv")
    assert "Paired differences" in report and "Limits" in report
    assert (tmp_path / "s.csv").exists()


def test_bootstrap_ci_brackets_mean():
    d = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    lo, hi = bootstrap_ci(d)
    assert lo <= d.mean() <= hi


def test_paired_comparison_counts():
    import pandas as pd

    scored = pd.DataFrame({
        "case_id": ["a", "a", "b", "b", "c", "c"],
        "version": ["v1", "v2"] * 3,
        "m": [1, 3, 2, 2, 4, 3],
    })
    pc = paired_comparisons(scored, "m").iloc[0]
    assert pc["comparison"] == "v2 vs v1"
    assert pc["v2_better"] == 1 and pc["v1_better"] == 1 and pc["ties"] == 1


def test_provider_selection(monkeypatch):
    from src import llm

    for k in ("LLM_PROVIDER", "GEMINI_API_KEY", "OPENAI_API_KEY", "GEMINI_MODEL", "OPENAI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert llm.provider() == "openai" and llm.resolve_base_url() is None
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    assert llm.provider() == "gemini"
    assert llm.resolve_api_key() == "g-test"
    assert llm.resolve_model() == llm.DEFAULT_GEMINI_MODEL
    assert llm.resolve_base_url() == llm.GEMINI_BASE_URL
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert llm.resolve_api_key() == "sk-test"


def test_retries_stop_on_fatal_errors():
    from src.live_eval import _with_retries

    calls = {"n": 0}

    def no_credit():
        calls["n"] += 1
        raise RuntimeError("Error code: 429 - insufficient_quota")

    try:
        _with_retries(no_credit, sleep=lambda s: None)
    except RuntimeError:
        pass
    assert calls["n"] == 1

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("429 rate limit, try again")
        return "ok"

    assert _with_retries(flaky, sleep=lambda s: None) == "ok" and attempts["n"] == 3


def test_chat_drops_unsupported_json_mode():
    from src.llm import chat

    class C:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kw):
            if "response_format" in kw:
                raise RuntimeError("response_format is not supported")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"score": 4}'))])

    assert chat(C(), "m", "s", "u", json_mode=True) == '{"score": 4}'
