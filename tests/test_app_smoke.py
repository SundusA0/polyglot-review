"""Headless smoke tests: every page renders without raising, and the review
flow (navigate, save an annotation, export) works end to end."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    # Keep the tests from touching the real annotations folder.
    from src import config

    monkeypatch.setattr(config, "ANNOTATIONS_DIR", tmp_path)
    monkeypatch.setattr(config, "ANNOTATIONS_CSV", tmp_path / "annotations.csv")
    monkeypatch.setattr(config, "PREFERENCES_CSV", tmp_path / "preferences.csv")


def _run_view(name: str, timeout: int = 90) -> AppTest:
    script = (
        "import sys, importlib\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"module = importlib.import_module('views.{name}')\n"
        "module.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=timeout)
    at.run()
    return at


def _assert_clean(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_app_entry_renders():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.run()
    _assert_clean(at)
    assert any("Polyglot Review" in t.value for t in at.title)


def test_overview_renders():
    at = _run_view("home")
    _assert_clean(at)
    assert at.metric[0].label == "Cases"


def test_compare_renders():
    at = _run_view("compare")
    _assert_clean(at)
    assert any("Compare versions" in t.value for t in at.title)


def test_real_model_comparison_defaults():
    at = _run_view("compare")
    _assert_clean(at)
    assert at.selectbox(key="compare_va").value == "v2-live"
    assert at.selectbox(key="compare_vb").value == "v3-live"


def test_real_model_review_defaults():
    at = _run_view("review")
    _assert_clean(at)
    assert at.selectbox(key="review_va").value == "v2-live"
    assert at.selectbox(key="review_vb").value == "v3-live"


def test_usage_renders_all_tabs():
    at = _run_view("usage")
    _assert_clean(at)
    labels = [m.label for m in at.metric]
    assert "Active users" in labels and "Feature events" in labels


def test_review_annotation_flow():
    at = _run_view("review")
    _assert_clean(at)
    assert at.selectbox(key="case_select").value == "pto_accrual-en"
    # The default is now real Gemini output; this older test explicitly selects
    # the injected-error demo so its existing assertions remain meaningful.
    at.selectbox(key="review_va").set_value("v1").run()
    _assert_clean(at)

    # Navigate with the "Next" button.
    next_button = [b for b in at.button if b.label.startswith("Next ▶")][0]
    next_button.click().run()
    _assert_clean(at)
    assert at.selectbox(key="case_select").value == "pto_accrual-fr"

    # Fill in and save an annotation for version A of that case.
    at.text_input(key="reviewer").set_value("tester").run()
    rid = "pto_accrual-fr-v1"
    at.segmented_control(key=f"hf_A{rid}").set_value(4)
    at.segmented_control(key=f"fl_A{rid}").set_value(5)
    at.text_area(key=f"notes_A{rid}").set_value("looks fine")
    save = [b for b in at.button if b.label == "Save annotation"][0]
    save.click().run()
    _assert_clean(at)
    ann = at.session_state["annotations"][rid]
    assert ann["human_factuality"] == 4 and ann["human_fluency"] == 5
    assert ann["reviewer"] == "tester" and ann["notes"] == "looks fine"

    # The export joins the annotation onto the scored response.
    from src.data import load_cases, load_glossary, load_responses
    from src.export import build_export
    from src.scoring import score_table

    scored = score_table(load_responses(), load_cases(), load_glossary())
    export = build_export(scored, load_cases(), {rid: ann}, {}, {}, only_annotated=True)
    assert len(export) == 1 and export.iloc[0]["reviewer"] == "tester"


def test_review_unreviewed_filter():
    at = _run_view("review")
    at.toggle(key="review_only_unreviewed").set_value(True).run()
    _assert_clean(at)
