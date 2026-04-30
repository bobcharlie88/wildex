from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import DR_GEMMA_LOCAL_FILES_ONLY, DR_GEMMA_MAX_NEW_TOKENS, DR_GEMMA_MODEL
from app.services.agents.schemas import DrAgentOutput

log = logging.getLogger("wildex.agents.gemma")


class LocalGemmaUnavailable(RuntimeError):
    pass


def _compact_context(payload: dict[str, Any]) -> dict[str, Any]:
    card = dict(payload.get("card") or {})
    return {
        "question": payload.get("question") or "",
        "mode": payload.get("mode") or "",
        "card_id": payload.get("card_id"),
        "capture_job_id": payload.get("capture_job_id"),
        "card": {
            key: card.get(key)
            for key in (
                "card_title",
                "species_name",
                "scientific_name",
                "rarity",
                "rarity_display",
                "biome",
                "region",
                "habitat_text",
                "diet",
                "diet_text",
                "fact_text",
                "fact_snippets",
            )
            if card.get(key) not in (None, "", [])
        },
        "biome": payload.get("biome") or card.get("biome") or card.get("habitat_text"),
        "player_region": payload.get("player_region") or card.get("region"),
        "collection": payload.get("collection") or {},
        "hunger_state": payload.get("hunger_state"),
        "feed_state": payload.get("feed_state"),
    }


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


@lru_cache(maxsize=1)
def _load_generator() -> Any:
    model_path = Path(DR_GEMMA_MODEL)
    if DR_GEMMA_LOCAL_FILES_ONLY and (model_path.is_absolute() or len(model_path.parts) > 1) and not model_path.exists():
        raise LocalGemmaUnavailable(
            f"Local Gemma model folder not found: {DR_GEMMA_MODEL}. "
            "Copy Gemma weights there or set DR_GEMMA_MODEL to the correct local folder."
        )

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
    except Exception as exc:  # pragma: no cover - depends on optional local ML stack
        raise LocalGemmaUnavailable(f"Local Gemma dependencies are unavailable: {exc}") from exc

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            DR_GEMMA_MODEL,
            local_files_only=DR_GEMMA_LOCAL_FILES_ONLY,
        )
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        model = AutoModelForCausalLM.from_pretrained(
            DR_GEMMA_MODEL,
            local_files_only=DR_GEMMA_LOCAL_FILES_ONLY,
            device_map="auto",
            torch_dtype=dtype,
        )
        return pipeline("text-generation", model=model, tokenizer=tokenizer)
    except Exception as exc:  # pragma: no cover - model files are machine-specific
        offline_hint = (
            " Put Gemma weights in the Hugging Face cache or set DR_GEMMA_MODEL to a local model folder."
            if DR_GEMMA_LOCAL_FILES_ONLY
            else ""
        )
        raise LocalGemmaUnavailable(f"Local Gemma could not be loaded from {DR_GEMMA_MODEL}.{offline_hint} {exc}") from exc


def _build_prompt(instructions: str, payload: dict[str, Any]) -> str:
    context = json.dumps(_compact_context(payload), ensure_ascii=True, default=str)
    return (
        "<start_of_turn>user\n"
        f"{instructions}\n\n"
        "Use this JSON context only:\n"
        f"{context}\n\n"
        "Return one compact JSON object with exactly these keys: "
        "mode, reply, follow_up, missing_context, suggested_actions, referenced_card_id, referenced_capture_job_id.\n"
        "Allowed mode values: card_explain, feeding_advice, biome_tip, what_next, read_aloud.\n"
        "Use null for follow_up when there is no follow-up. Use arrays for missing_context and suggested_actions.\n"
        "<end_of_turn>\n"
        "<start_of_turn>model\n"
    )


def generate_dr_response_with_gemma(payload: dict[str, Any], instructions: str) -> DrAgentOutput:
    generator = _load_generator()
    prompt = _build_prompt(instructions, payload)
    try:
        generated = generator(
            prompt,
            max_new_tokens=DR_GEMMA_MAX_NEW_TOKENS,
            do_sample=False,
            return_full_text=False,
        )
        text = generated[0]["generated_text"] if generated else ""
        parsed = _extract_json(text)
        parsed.setdefault("referenced_card_id", payload.get("card_id"))
        parsed.setdefault("referenced_capture_job_id", payload.get("capture_job_id"))
        return DrAgentOutput.model_validate(parsed)
    except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
        log.warning("Local Gemma generated invalid DR output; falling back. error=%s", exc)
        raise LocalGemmaUnavailable(f"Local Gemma produced invalid structured output: {exc}") from exc
