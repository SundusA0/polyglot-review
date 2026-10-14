"""Text normalisation, number extraction, sentence splitting and a small
language heuristic. Everything here is dependency-free so it can run anywhere.

The language detector is deliberately simple (script ranges + stopword votes).
It is good enough to catch an answer that came back in the wrong language or
that has an English sentence pasted into it, which is what the review app needs.
Swap in a real model (fastText, langdetect) if you need finer distinctions.
"""
from __future__ import annotations

import re
import unicodedata

from .config import DECIMAL_COMMA_LANGUAGES

# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
# Collapse Arabic letter variants so prefixes/suffixes don't break substring matches.
_ARABIC = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ـ": ""})
# Kana voicing marks are combining characters we must keep (が must not become か).
_KEEP_MARKS = {"゙", "゚"}


def normalize(text: str) -> str:
    """Casefold, strip accents/diacritics, unify quotes and whitespace.

    Both sides of every comparison go through this, so what matters is
    consistency rather than linguistic purity.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).translate(_ARABIC)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn" or ch in _KEEP_MARKS)
    text = unicodedata.normalize("NFC", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #

_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}:\d{2})(?!\d)")
# A number token must not start inside another number ("25" in "1.25") and must not
# continue into one, but a trailing sentence period ("...over $25.") is fine.
_BEFORE = r"(?<![\d.,])"
_AFTER = r"(?!\d)(?![.,]\d)"
_NUM_RE = re.compile(_BEFORE + r"(\d+(?:[.,]\d+)*)" + _AFTER)
_CURRENCY = "$€£¥"


def parse_number(token: str, language: str) -> str | None:
    """Canonicalise a numeric token ("1,25" in French -> "1.25", "1,500" in English -> "1500")."""
    token = token.strip()
    if not token:
        return None
    dec = "," if language in DECIMAL_COMMA_LANGUAGES else "."
    thou = "." if dec == "," else ","
    # Thousands separators are only accepted in groups of three.
    if thou in token and re.fullmatch(rf"\d{{1,3}}(?:\{thou}\d{{3}})+(?:\{dec}\d+)?", token):
        token = token.replace(thou, "")
    if dec in token:
        token = token.replace(dec, ".")
    try:
        value = float(token)
    except ValueError:
        return None
    return f"{value:g}"


def extract_numbers(text: str, language: str) -> list[str]:
    """Return canonical number tokens found in text (times like 17:00 are kept as-is)."""
    if not text:
        return []
    text = unicodedata.normalize("NFKC", text)
    found: list[str] = []
    for t in _TIME_RE.findall(text):
        found.append(t)
    stripped = _TIME_RE.sub(" ", text)
    for raw in _NUM_RE.findall(stripped):
        canon = parse_number(raw, language)
        if canon is not None:
            found.append(canon)
    return found


def numeric_core(fact: str) -> str | None:
    """If a key fact is essentially a number ("15", "1,25", "100 %", "$25"), return the digits part."""
    cleaned = unicodedata.normalize("NFKC", fact).strip()
    cleaned = cleaned.strip(_CURRENCY + " ").replace("%", "").strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", cleaned):
        return cleaned
    return None


def number_present(core: str, text: str) -> bool:
    """True when the number appears as a standalone token (so "15" doesn't match inside "150" or "1.5")."""
    norm_text = unicodedata.normalize("NFKC", text)
    pattern = _BEFORE + re.escape(core) + _AFTER
    return re.search(pattern, norm_text) is not None


# --------------------------------------------------------------------------- #
# Sentences
# --------------------------------------------------------------------------- #

_LATIN_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ¡¿«\"'(])")
# German ordinals ("31. März") must not end a sentence.
_GERMAN_SPLIT = re.compile(r"(?<=[.!?])(?<!\d\.)\s+(?=[A-ZÀ-ÖØ-Þ¡¿«\"'(])")
_CJK_SPLIT = re.compile(r"(?<=[。！？])")
_ARABIC_SPLIT = re.compile(r"(?<=[.!?؟])\s+")


def split_sentences(text: str, language: str) -> list[str]:
    """Split text into sentences without breaking "p. m." or German ordinals."""
    text = text.strip()
    if not text:
        return []
    if language == "ja":
        parts = _CJK_SPLIT.split(text)
    elif language == "ar":
        parts = _ARABIC_SPLIT.split(text)
    elif language == "de":
        parts = _GERMAN_SPLIT.split(text)
    else:
        parts = _LATIN_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def join_sentences(parts: list[str], language: str) -> str:
    return "".join(parts) if language == "ja" else " ".join(parts)


_TERMINALS = ".!?。！？؟…)\"'»」"


def is_truncated(text: str) -> bool:
    """A response that stops without terminal punctuation was probably cut off."""
    stripped = text.rstrip()
    if not stripped:
        return True
    return stripped[-1] not in _TERMINALS


# --------------------------------------------------------------------------- #
# Language heuristic
# --------------------------------------------------------------------------- #

STOPWORDS: dict[str, set[str]] = {
    "en": {
        "the", "and", "you", "your", "is", "are", "to", "of", "for", "with", "will", "can", "if",
        "this", "that", "be", "have", "please", "within", "by", "at", "any", "before", "let",
        "know", "there", "anything", "else", "help", "it", "we", "our", "as", "from", "after",
        "should", "must", "when", "what", "how", "do", "does", "not", "up", "into", "each",
        "which", "just", "keep", "mind", "need", "needs", "get", "make", "sure", "once", "also",
        "only", "applies", "note", "here",
    },
    "fr": {
        "le", "la", "les", "des", "de", "du", "vous", "votre", "vos", "est", "sont", "et", "pour",
        "avec", "dans", "une", "un", "par", "que", "qui", "ne", "pas", "sur", "au", "aux", "peut",
        "peuvent", "avant", "si", "ce", "cette", "ces", "plus", "tous", "toute", "à", "être", "ou",
        "sous", "entre", "chaque", "nous", "leur", "leurs", "doivent", "doit", "en", "jusqu",
    },
    "es": {
        "el", "la", "los", "las", "de", "del", "que", "y", "para", "con", "su", "sus", "es", "son",
        "se", "en", "un", "una", "por", "al", "usted", "puede", "pueden", "antes", "dentro",
        "como", "cada", "hasta", "si", "lo", "le", "más", "también", "debe", "deben", "después",
        "cualquier", "sobre", "ese", "esa", "este", "esta", "o",
    },
    "de": {
        "der", "die", "das", "und", "sie", "ihr", "ihre", "ihren", "ist", "sind", "für", "mit",
        "im", "in", "ein", "eine", "einen", "einem", "zu", "von", "bei", "auf", "werden", "wird",
        "können", "bitte", "vor", "nach", "oder", "dass", "nicht", "alle", "über", "als", "wenn",
        "bis", "zum", "zur", "des", "dem", "den", "pro", "am", "noch", "gerne", "jeden", "jedes",
        "wie", "ihrer", "ihres",
    },
}

_WORD_RE = re.compile(r"[^\W\d_]+")


def script_shares(text: str) -> dict[str, float]:
    """Fraction of letters in each script family (arabic, japanese, latin)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return {"arabic": 0.0, "japanese": 0.0, "latin": 0.0}
    arabic = sum(1 for ch in letters if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ")
    japanese = sum(
        1 for ch in letters
        if "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" or "ｦ" <= ch <= "ﾟ"
    )
    latin = sum(1 for ch in letters if ch.isascii() or "À" <= ch <= "ɏ")
    n = len(letters)
    return {"arabic": arabic / n, "japanese": japanese / n, "latin": latin / n}


def stopword_votes(text: str) -> dict[str, int]:
    words = _WORD_RE.findall(text.casefold().replace("'", " "))
    return {lang: sum(1 for w in words if w in vocab) for lang, vocab in STOPWORDS.items()}


def detect_language(text: str) -> tuple[str | None, float, dict[str, int]]:
    """Return (language_code or None, confidence 0-1, stopword votes)."""
    votes = stopword_votes(text)
    shares = script_shares(text)
    if shares["arabic"] >= 0.3:
        return "ar", shares["arabic"], votes
    if shares["japanese"] >= 0.3:
        return "ja", shares["japanese"], votes
    total = sum(votes.values())
    if total == 0:
        return None, 0.0, votes
    best = max(votes, key=votes.get)
    if votes[best] < 3:
        return None, 0.0, votes
    return best, votes[best] / total, votes


def has_english_passage(text: str, expected: str) -> bool:
    """True when a response in another language also contains a run of English.

    For Latin-script languages both languages must be clearly present (the
    expected language's stopwords and at least four English ones); an answer
    that is entirely English is a wrong-language case, not a mixed one.
    """
    if expected == "en":
        return False
    votes = stopword_votes(text)
    en = votes.get("en", 0)
    if expected in ("ja", "ar"):
        return en >= 3
    return en >= 4 and votes.get(expected, 0) >= 3
