"""Optional OpenAI calls: generate a response for a prompt version, grade a
response with an LLM judge, and draft a short usage narrative.

Nothing in the app depends on these; without an API key the buttons are hidden.
The model name comes from OPENAI_MODEL and defaults to a small, cheap chat model.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .config import DEFAULT_OPENAI_MODEL, PROMPTS_DIR
from .data import Glossary, load_prompt_template, render_template


class LLMNotConfigured(RuntimeError):
    pass


def resolve_api_key(override: str | None = None) -> str | None:
    key = (override or "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    return key or None


def resolve_model(override: str | None = None) -> str:
    return (override or "").strip() or os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL


def make_client(api_key: str | None):
    if not api_key:
        raise LLMNotConfigured("Set OPENAI_API_KEY (or paste a key in the sidebar) to enable live calls.")
    from openai import OpenAI  # imported lazily so the app works without the package configured

    return OpenAI(api_key=api_key)


def chat(client, model: str, system: str, user: str, json_mode: bool = False) -> str:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = client.chat.completions.create(temperature=0, **kwargs)
    except Exception as exc:  # reasoning models reject a custom temperature
        if "temperature" in str(exc).lower():
            resp = client.chat.completions.create(**kwargs)
        else:
            raise
    return (resp.choices[0].message.content or "").strip()


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
