import json
import os

import google.generativeai as genai

_model = None


def _get_model():
    global _model
    if _model is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel("gemini-2.0-flash")
    return _model


def generate_insights(prompt: str) -> list[str]:
    model = _get_model()

    response = model.generate_content(prompt)
    raw = response.text.strip()

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

    return [str(item) for item in insights[:5]]
