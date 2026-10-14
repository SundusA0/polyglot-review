import pytest

from src.data import load_cases, load_glossary, load_responses
from src.scoring import calibration, clean_false_positive_rate, score_response, score_table
from src.textnorm import (
    detect_language,
    extract_numbers,
    has_english_passage,
    is_truncated,
    normalize,
    parse_number,
    split_sentences,
)


@pytest.fixture(scope="module")
def glossary():
    return load_glossary()


@pytest.fixture(scope="module")
def cases():
    return load_cases()


def case(cases, case_id):
    return cases.loc[cases["case_id"] == case_id].iloc[0].to_dict()


# --- normalisation ---------------------------------------------------------- #

def test_normalize_strips_accents_and_case():
    assert normalize("Congés Payés") == "conges payes"
    assert normalize("Überstunden") == "uberstunden"
    assert normalize("d’adhésion") == "d'adhesion"


def test_normalize_keeps_kana_voicing():
    assert normalize("が") != normalize("か")


def test_normalize_arabic_variants():
    assert normalize("الإجازة") == normalize("الاجازة")


# --- numbers ---------------------------------------------------------------- #

@pytest.mark.parametrize("token,lang,expected", [
    ("1,25", "fr", "1.25"), ("1.25", "en", "1.25"), ("1,500", "en", "1500"), ("1.500", "de", "1500"),
    ("15", "ja", "15"), ("100", "ar", "100"),
])
def test_parse_number(token, lang, expected):
    assert parse_number(token, lang) == expected


def test_extract_numbers_handles_times_and_sentence_ends():
    nums = extract_numbers("Submit by 5:00 p.m. on Monday; cheques take 3 days. Receipts over $25.", "en")
    assert "5:00" in nums and "3" in nums and "25" in nums
    assert "5" not in nums  # the 5 inside 5:00 must not leak out


def test_extract_numbers_decimal_comma():
    assert extract_numbers("1,25 jour par mois, soit 15 jours", "fr") == ["1.25", "15"]


# --- sentences -------------------------------------------------------------- #

def test_split_keeps_german_ordinals_and_spanish_pm():
    de = split_sentences("Bis zum 31. März genommen werden. Danach nicht mehr.", "de")
    assert len(de) == 2
    es = split_sentences("Antes de las 5:00 p. m. del lunes. Después no.", "es")
    assert len(es) == 2


def test_split_japanese():
    assert len(split_sentences("毎月1.25日です。年間で15日になります。", "ja")) == 2


def test_truncation_detection():
    assert is_truncated("Overtime needs to be approved by your")
    assert not is_truncated("Overtime needs to be approved by your manager.")
    assert not is_truncated("申請してください。")


# --- language --------------------------------------------------------------- #

@pytest.mark.parametrize("text,lang", [
    ("You are paid biweekly on Fridays and your timesheet is due on Monday.", "en"),
    ("Vous êtes payé toutes les deux semaines, le vendredi, et la feuille de temps est due le lundi.", "fr"),
    ("Se le paga cada dos semanas, los viernes, y la hoja de horas debe enviarse el lunes.", "es"),
    ("Sie werden alle zwei Wochen bezahlt und der Stundenzettel ist am Montag fällig.", "de"),
    ("給与は隔週の金曜日に支払われます。タイムシートは月曜日までに提出してください。", "ja"),
    ("يُدفع راتبك كل أسبوعين يوم الجمعة ويجب تقديم جدول الحضور يوم الاثنين.", "ar"),
])
def test_detect_language(text, lang):
    assert detect_language(text)[0] == lang


def test_english_passage_in_french():
    text = ("Vous êtes payé toutes les deux semaines, le vendredi. Let me know if there's anything else I can help "
            "with!")
    assert has_english_passage(text, "fr")
    assert not has_english_passage("Vous êtes payé toutes les deux semaines, le vendredi.", "fr")


# --- scoring ---------------------------------------------------------------- #

def test_clean_response_scores_full(cases, glossary):
    c = case(cases, "pto_accrual-en")
    s = score_response(c, c["reference_answer"], glossary)
    assert s.factuality.score == 100
    assert s.terminology.score == 100
    assert s.suggested_tags == []


def test_wrong_number_detected(cases, glossary):
    c = case(cases, "pto_accrual-fr")
    text = c["reference_answer"].replace("15 jours", "12 jours")
    s = score_response(c, text, glossary)
    assert "wrong_number" in s.suggested_tags
    assert "12" in s.factuality.numeric_conflicts
    assert "15" in s.factuality.facts_missing


def test_omission_detected(cases, glossary):
    c = case(cases, "overtime-en")
    text = "Non-exempt employees receive overtime pay at 1.5 times their regular hourly rate for hours beyond 40."
    s = score_response(c, text, glossary)
    assert "omission" in s.suggested_tags
    assert "in advance" in s.factuality.facts_missing


def test_terminology_avoid_term(cases, glossary):
    c = case(cases, "pay_schedule-es")
    text = c["reference_answer"].replace("cada dos semanas", "quincenalmente").replace("quincenalmente", "quincenal")
    s = score_response(c, text, glossary)
    assert "terminology_mismatch" in s.suggested_tags
    assert ("pay_period", "quincenal") in s.terminology.avoid_hits


def test_short_avoid_term_needs_word_boundary(cases, glossary):
    c = case(cases, "overtime-en")
    # "OT" is a discouraged term but must not match inside "other" or "not".
    text = c["reference_answer"] + " Nothing else is other than that."
    s = score_response(c, text, glossary)
    assert not s.terminology.avoid_hits


def test_french_avoid_prefix_does_not_fire(cases, glossary):
    c = case(cases, "overtime-fr")
    s = score_response(c, c["reference_answer"], glossary)
    assert not s.terminology.avoid_hits  # "heures sup" must not match "heures supplémentaires"


def test_wrong_language(cases, glossary):
    c = case(cases, "parental_leave-de")
    en = case(cases, "parental_leave-en")["reference_answer"]
    s = score_response(c, en, glossary)
    assert s.suggested_tags == ["wrong_language"]


def test_invented_year_is_flagged_as_hallucination(cases, glossary):
    c = case(cases, "benefits_enrollment-ja")
    text = c["reference_answer"] + "このポリシーは2019年に最終更新されました。"
    s = score_response(c, text, glossary)
    assert "2019" in s.factuality.numeric_conflicts
    assert "hallucination" in s.suggested_tags
    assert "wrong_number" not in s.suggested_tags


# --- calibration against injected errors ------------------------------------ #

def test_calibration_on_bundled_data(cases, glossary):
    scored = score_table(load_responses(), cases, glossary)
    cal = calibration(scored).set_index("tag")
    for tag in ["wrong_number", "terminology_mismatch", "wrong_language", "untranslated_text", "truncated"]:
        assert cal.loc[tag, "recall"] >= 0.9, tag
        assert cal.loc[tag, "precision"] >= 0.9, tag
    assert cal.loc["omission", "recall"] >= 0.8
    assert clean_false_positive_rate(scored) <= 0.05


def test_versions_rank_as_expected(cases, glossary):
    scored = score_table(load_responses(), cases, glossary)
    means = scored.groupby("prompt_version")["factuality_auto"].mean()
    assert means["v1"] < means["v2"] < means["v3"]
