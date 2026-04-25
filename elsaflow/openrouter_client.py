from __future__ import annotations

import json
import re

import requests

from elsaflow.models import ModelVote, ResearchReport


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
MODEL_ALIASES = {
    "chatgpt": DEFAULT_OPENROUTER_MODEL,
    "deepseek": DEFAULT_OPENROUTER_MODEL,
    "grok": DEFAULT_OPENROUTER_MODEL,
    "gemini": DEFAULT_OPENROUTER_MODEL,
    "nemotron": DEFAULT_OPENROUTER_MODEL,
}


def normalize_openrouter_model(model_name: str) -> str:
    cleaned = model_name.strip()
    if not cleaned:
        return DEFAULT_OPENROUTER_MODEL
    lowered = cleaned.lower()
    if lowered in MODEL_ALIASES:
        return MODEL_ALIASES[lowered]
    if "/" not in cleaned:
        return DEFAULT_OPENROUTER_MODEL
    return cleaned


def _extract_json_block(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except Exception:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))

    brace = re.search(r"(\{.*\})", content, flags=re.DOTALL)
    if brace:
        return json.loads(brace.group(1))

    raise ValueError("No JSON object found in model response")


def _heuristic_vote(model_name: str, research: ResearchReport, reason_suffix: str) -> ModelVote:
    resolved_model = normalize_openrouter_model(model_name)
    base_confidence = max(0.1, min(0.95, (research.confidence_score + abs(research.sentiment_score)) / 2))
    if research.sentiment_score > 0.25:
        decision = "YES"
        rationale = "Signals lean positive and suggest a favorable probability skew."
    elif research.sentiment_score < -0.05:
        decision = "NO"
        rationale = "Signals lean negative and suggest avoiding or opposing the thesis."
    else:
        decision = "SKIP"
        rationale = "Signals are mixed and do not justify a trade."
    return ModelVote(
        model_name=model_name,
        decision=decision,
        confidence=base_confidence,
        rationale=f"{rationale} {reason_suffix}".strip(),
        provider_status="heuristic",
        provider_model=resolved_model,
    )


def request_openrouter_vote(
    model_name: str,
    research: ResearchReport,
    openrouter_api_key: str,
) -> ModelVote:
    resolved_model = normalize_openrouter_model(model_name)
    if not openrouter_api_key.strip():
        return _heuristic_vote(model_name, research, "Fallback heuristic used because no OpenRouter key is configured.")

    system_prompt = (
        "You are an analyst for a prediction-market paper trading agent. "
        "Return strict JSON with keys: decision, confidence, rationale. "
        "decision must be YES, NO, or SKIP. confidence must be a number between 0 and 1. "
        "rationale must be one short sentence."
    )
    signal_lines = "\n".join(
        f"- {signal.source}: {signal.title} | sentiment={signal.sentiment_score:.2f} | relevance={signal.relevance_score:.2f}"
        for signal in research.signals[:8]
    )
    user_prompt = (
        f"Topic: {research.market_topic or research.category}\n"
        f"Category: {research.category}\n"
        f"Research summary: {research.summary}\n"
        f"Average sentiment: {research.sentiment_score:.2f}\n"
        f"Average confidence: {research.confidence_score:.2f}\n"
        f"Signals:\n{signal_lines}\n"
        "Decide whether a paper trading agent should take a YES trade, a NO trade, or SKIP."
    )
    payload = {
        "model": resolved_model,
        "temperature": 0.2,
        "max_tokens": 120,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8501",
        "X-Title": "ElsaFlow",
    }
    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_json = response.json()
        content = response_json["choices"][0]["message"]["content"]
        parsed = _extract_json_block(content)
        decision = str(parsed.get("decision", "SKIP")).upper().strip()
        if decision not in {"YES", "NO", "SKIP"}:
            decision = "SKIP"
        confidence = float(parsed.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        rationale = str(parsed.get("rationale", "")).strip() or "OpenRouter model returned an empty rationale."
        request_preview = json.dumps(
            {
                "model": resolved_model,
                "topic": research.market_topic or research.category,
                "avg_sentiment": round(research.sentiment_score, 2),
                "avg_confidence": round(research.confidence_score, 2),
                "signal_count": len(research.signals),
            }
        )
        return ModelVote(
            model_name=model_name,
            decision=decision,
            confidence=confidence,
            rationale=f"{rationale} OpenRouter live call succeeded.",
            provider_status="live",
            provider_model=response_json.get("model", resolved_model),
            request_preview=request_preview,
            response_preview=content[:1200],
        )
    except Exception as exc:
        vote = _heuristic_vote(model_name, research, f"Fallback heuristic used because OpenRouter request failed: {exc}.")
        vote.request_preview = json.dumps(
            {
                "model": resolved_model,
                "topic": research.market_topic or research.category,
                "avg_sentiment": round(research.sentiment_score, 2),
                "avg_confidence": round(research.confidence_score, 2),
                "signal_count": len(research.signals),
            }
        )
        vote.response_preview = str(exc)
        return vote
