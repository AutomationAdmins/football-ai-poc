import json
import os
import re

from openai import OpenAI

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is not set")
        _client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
    return _client


def _extract_numbers(text: str) -> set[str]:
    """Returns all numeric tokens found in a string."""
    return set(re.findall(r'\b\d+(?:\.\d+)?\b', text))


def _ground_insights(insights: list[str], allowed_facts: dict) -> list[str]:
    """Removes any insight containing a number not present in the supplied facts."""
    allowed_numbers = set()
    for v in allowed_facts.values():
        allowed_numbers.update(_extract_numbers(str(v)))

    grounded = []
    for insight in insights:
        numbers_in_insight = _extract_numbers(insight)
        if numbers_in_insight.issubset(allowed_numbers):
            grounded.append(insight)
        # silently drop insights that reference numbers not in supplied stats

    return grounded


def generate_insights(prompt: str, allowed_facts: dict) -> list[str]:
    client = _get_client()

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,  # deterministic — zero tolerance for creative invention
        max_tokens=512,
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Extract JSON array if buried in surrounding text
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON array found in AI response: {raw[:200]}")
    raw = raw[start:end]

    insights = json.loads(raw)

    if not isinstance(insights, list):
        raise ValueError("AI response was not a JSON array")

    insights = [str(item) for item in insights[:5]]

    # Grounding check — strip any insight containing a hallucinated number
    grounded = _ground_insights(insights, allowed_facts)

    if not grounded:
        raise ValueError("All AI insights were rejected by the grounding validator — no verified facts found.")

    return grounded
