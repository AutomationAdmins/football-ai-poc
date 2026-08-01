import json
import os
import re

from openai import OpenAI

_client = None


def _get_client():

    global _client

    if _client is None:

        api_key = os.environ.get("GROQ_API_KEY")

        if not api_key:
            raise ValueError("GROQ_API_KEY not configured")

        _client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
        )

    return _client


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


def _chat(prompt: str, max_tokens=800):

    client = _get_client()

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        temperature=0,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.choices[0].message.content


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

def _ground_insights(insights, allowed_facts):

    allowed_numbers = set()

    for value in allowed_facts.values():
        allowed_numbers.update(
            _extract_numbers(str(value))
        )

    grounded = []

    for insight in insights:

        nums = _extract_numbers(insight)

        if nums.issubset(allowed_numbers):
            grounded.append(insight)

    return grounded


def generate_insights(prompt, allowed_facts):

    raw = _chat(prompt)

    raw = _strip_json(raw)

    start = raw.find("[")
    end = raw.rfind("]") + 1

    if start == -1:
        raise ValueError("No JSON array returned.")

    insights = json.loads(raw[start:end])

    insights = [
        str(x)
        for x in insights[:5]
    ]

    grounded = _ground_insights(
        insights,
        allowed_facts
    )

    if not grounded:
        raise ValueError(
            "Every insight failed grounding."
        )

    return grounded