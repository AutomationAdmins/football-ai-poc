import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

# Load environment variables from .env file
load_dotenv()


class GroqRateLimitError(Exception):
    """Raised when the Groq daily token quota is exhausted."""
    def __init__(self, retry_after: str = "unknown"):
        self.retry_after = retry_after
        super().__init__(f"Groq rate limit reached. Retry in: {retry_after}")


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


def _chat(prompt: str, max_tokens=800):

    client = _get_client()

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            #model="llama-3.1-8b-instant",
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

    except RateLimitError as e:
        # Parse retry time from Groq error message if present
        retry_after = "unknown"
        try:
            msg = str(e)
            match = re.search(r"Please try again in ([\d]+m[\d.]+s|[\d.]+s)", msg)
            if match:
                retry_after = match.group(1)
        except Exception:
            pass
        raise GroqRateLimitError(retry_after=retry_after) from e


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