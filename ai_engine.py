import json
import os
import re

import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

_PROJECT = os.environ.get("GCP_PROJECT", "avid-invention-484506-g9")
_REGION = os.environ.get("GCP_REGION", "us-central1")
_MODEL = os.environ.get("VERTEX_MODEL", "gemini-1.5-flash-002")

vertexai.init(project=_PROJECT, location=_REGION)
_model = GenerativeModel(_MODEL)


# ---------------------------------------------------------
# Generic Helpers
# ---------------------------------------------------------

def _extract_numbers(text: str):

    return set(re.findall(r"\b\d+(?:\.\d+)?\b", text))


def _strip_json(raw: str):

    raw = raw.strip()

    if "```" in raw:

        raw = raw.split("```")[1]

        if raw.startswith("json"):
            raw = raw[4:]

        raw = raw.strip()

    return raw


def flatten_for_grounding(obj, result=None):

    if result is None:
        result = {}

    if isinstance(obj, dict):
        for value in obj.values():
            flatten_for_grounding(value, result)

    elif isinstance(obj, list):
        for item in obj:
            flatten_for_grounding(item, result)

    else:
        result[str(len(result))] = obj

    return result


def _allowed_numbers(allowed_facts):

    allowed_numbers = set()

    for value in allowed_facts.values():
        allowed_numbers.update(
            _extract_numbers(str(value))
        )

    return allowed_numbers


def _is_grounded(text, allowed_facts):

    if not text:
        return False

    allowed_numbers = _allowed_numbers(allowed_facts)
    nums = _extract_numbers(text)

    return nums.issubset(allowed_numbers)


def _chat(prompt: str, max_tokens: int = 800) -> str:
    cfg = GenerationConfig(temperature=0, max_output_tokens=max_tokens)
    response = _model.generate_content(prompt, generation_config=cfg)
    return response.text


# ---------------------------------------------------------
# Editorial Ranking
# ---------------------------------------------------------

def rank_events(prompt: str):

    raw = _chat(prompt)

    raw = _strip_json(raw)

    start = raw.find("{")
    end = raw.rfind("}") + 1

    if start == -1:
        raise ValueError("Editorial engine returned invalid JSON.")

    result = json.loads(raw[start:end])

    if "ranking" not in result:
        raise ValueError("Missing ranking.")

    return result


# ---------------------------------------------------------
# Insight Generation
# ---------------------------------------------------------

def generate_insights(prompt, allowed_facts):

    raw = _chat(prompt, max_tokens=1200)

    raw = _strip_json(raw)

    start = raw.find("{")
    end = raw.rfind("}") + 1

    if start == -1:
        raise ValueError("No JSON object returned.")

    data = json.loads(raw[start:end])

    lead_story = str(data.get("lead_story", "")).strip()

    if not lead_story:
        raise ValueError("Missing lead_story.")

    if not _is_grounded(lead_story, allowed_facts):
        raise ValueError("Lead story failed grounding.")

    grounded_insights = []

    for item in data.get("insights", [])[:5]:

        if isinstance(item, str):
            line = item.strip()
            category = "stat"
            facts_used = []
        else:
            line = str(item.get("line", "")).strip()
            category = str(item.get("category", "stat"))
            facts_used = item.get("facts_used", [])

        if not line:
            continue

        if _is_grounded(line, allowed_facts):
            grounded_insights.append({
                "category": category,
                "line": line,
                "facts_used": facts_used,
            })

    if not grounded_insights:
        raise ValueError(
            "Every insight failed grounding."
        )

    return {
        "lead_story": lead_story,
        "insights": grounded_insights,
    }