"""Optional model calls: generate a response for a prompt version, grade a
response with an LLM judge, and draft a short usage narrative.

Nothing in the app depends on these; without an API key the buttons are hidden.

Two providers work through the same OpenAI client:

* OpenAI      - OPENAI_API_KEY, model from OPENAI_MODEL (default gpt-4.1-mini)
* Google Gemini (free tier) - GEMINI_API_KEY, model from GEMINI_MODEL
                (default gemini-flash-latest), via Gemini's OpenAI-compatible endpoint

Gemini is used when GEMINI_API_KEY is set, unless LLM_PROVIDER=openai.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .config import DEFAULT_OPENAI_MODEL, PROMPTS_DIR
from .data import Glossary, load_prompt_template, render_template

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"


class LLMNotConfigured(RuntimeError):
    pass


def provider() -> str:
    """'openai' or 'gemini'."""
    chosen = os.getenv("LLM_PROVIDER", "").strip().lower()
    if chosen in ("openai", "gemini"):
        return chosen
    return "gemini" if os.getenv("GEMINI_API_KEY", "").strip() else "openai"


def resolve_api_key(override: str | None = None) -> str | None:
    env = "GEMINI_API_KEY" if provider() == "gemini" else "OPENAI_API_KEY"
    key = (override or "").strip() or os.getenv(env, "").strip()
    return key or None


def resolve_model(override: str | None = None) -> str:
    if (override or "").strip():
        return override.strip()
    if provider() == "gemini":
        return os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
    return os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL


def resolve_base_url() -> str | None:
    if provider() == "gemini":
        return GEMINI_BASE_URL
    return os.getenv("OPENAI_BASE_URL", "").strip() or None


def make_client(api_key: str | None, base_url: str | None = None):
    if not api_key:
        raise LLMNotConfigured(
            "Set OPENAI_API_KEY or GEMINI_API_KEY in .env (or paste a key in the sidebar) to enable live calls."
        )
    from openai import OpenAI  # imported lazily so the app works without the package configured

    return OpenAI(api_key=api_key, base_url=base_url or resolve_base_url())


def chat(client, model: str, system: str, user: str, json_mode: bool = False) -> str:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    # Some models reject a custom temperature or JSON mode; drop the option and retry.
    for _ in range(3):
        try:
            resp = client.chat.completions.create(**kwargs)
            break
        except Exception as exc:
            msg = str(exc).lower()
            if "temperature" in msg and "temperature" in kwargs:
                kwargs.pop("temperature")
            elif "response_format" in msg and "response_format" in kwargs:
                kwargs.pop("response_format")
            else:
                raise
    else:
        resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message if resp.choices else None
    return ((msg.content if msg else None) or "").strip()


def build_system_prompt(version: str, case: dict, glossary: Glossary) -> str:
    template = load_prompt_template(version)
    concepts = case.get("required_concepts_list") or []
    return render_template(
        template,
        language_name=case["language_name"],
        context=case["context"],
        glossary_block=glossary.prompt_block(case["language"], concepts or None),
    )


def generate_response(client, model: str, version: str, case: dict, glossary: Glossary) -> str:
    system = build_system_prompt(version, case, glossary)
    return chat(client, model, system, case["question"])


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    score = re.search(r"\b([1-5])\b", cleaned)
    return {"score": int(score.group(1)) if score else None, "rationale": cleaned[:500],
            "unsupported_claims": [], "missing_facts": [], "language_ok": None}


def judge_factuality(client, model: str, case: dict, response: str) -> dict:
    template = (PROMPTS_DIR / "judge_factuality.md").read_text(encoding="utf-8")
    prompt = render_template(
        template,
        language_name=case["language_name"],
        context=case["context"],
        question=case["question"],
        reference=case["reference_answer"],
        response=response,
    )
    raw = chat(client, model, "You are a careful, strict grader. Reply with JSON only.", prompt, json_mode=True)
    result = _parse_json(raw)
    try:
        result["score"] = int(result.get("score")) if result.get("score") is not None else None
    except (TypeError, ValueError):
        result["score"] = None
    result.setdefault("rationale", "")
    result.setdefault("unsupported_claims", [])
    result.setdefault("missing_facts", [])
    result.setdefault("language_ok", None)
    result["model"] = model
    return result


def narrate_usage(client, model: str, insights: list[str], summary_table_md: str) -> str:
    system = (
        "You write short, factual product-analytics updates for stakeholders. "
        "Use only the numbers provided. No marketing language. Markdown, under 180 words."
    )
    user = (
        "Observations:\n" + "\n".join(f"- {i}" for i in insights)
        + "\n\nFeature table:\n" + summary_table_md
        + "\n\nWrite a three-paragraph update: what is working, what needs attention, and one recommended next step."
    )
    return chat(client, model, system, user)
