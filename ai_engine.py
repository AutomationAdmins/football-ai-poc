import json
import os
import re

from openai import OpenAI

_API_KEY = os.environ.get("GROQ_API_KEY")
_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=_API_KEY, base_url="https://api.groq.com/openai/v1")
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


def _chat(prompt: str, max_tokens: int = 800) -> str:
    response = _get_client().chat.completions.create(
        model=_MODEL,
        temperature=0,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def _fallback_lead_story(editorial_context: dict) -> str:
    event = editorial_context.get("event", {}) if isinstance(editorial_context, dict) else {}
    facts = editorial_context.get("commentator_facts", {}) if isinstance(editorial_context, dict) else {}

    player = event.get("player") or facts.get("player") or "The player"
    team = event.get("team") or facts.get("team") or "the team"
    opponent = event.get("opponent") or facts.get("opponent") or "the opponent"
    minute = event.get("minute") or facts.get("minute") or ""
    score = event.get("score") or facts.get("score") or ""
    event_type = str(event.get("event_type") or "GOAL").upper()

    if event_type == "RED_CARD":
        lead = f"{player} is sent off for {team} against {opponent} at {minute}'. {score}."
    elif event_type == "HALF_TIME":
        lead = f"Half-time in {team} vs {opponent} — {score} at {minute}'."
    elif event_type == "FULL_TIME":
        lead = f"Full-time in {team} vs {opponent} — {score} at {minute}'."
    elif event_type == "VAR_DECISION":
        lead = f"VAR decision in {team} vs {opponent} at {minute}' — {score}."
    elif event_type == "PENALTY":
        lead = f"{player} scores a penalty for {team} against {opponent} — {score} at {minute}'."
    elif event_type == "OWN_GOAL":
        lead = f"{player} scores an own goal for {team} against {opponent} — {score} at {minute}'."
    else:
        lead = f"{player} scores for {team} against {opponent} — {score} at {minute}'."

    # We no longer aggressively append consequence_bits to the fallback lead
    # because it causes massive repetition on the frontend.
    return lead.strip()


def _fallback_insights(editorial_context: dict) -> list[dict]:
    facts = editorial_context.get("commentator_facts", {}) if isinstance(editorial_context, dict) else {}
    insights = []

    for category, key in (
        ("milestone", "player_highlight"),
        ("league_impact", "promotion_stakes"),
        ("league_impact", "champions_league_stakes"),
        ("league_impact", "title_race"),
        ("match_context", "what_happened"),
        ("player_stat", "player_highlight"),
        ("team_stat", "team_highlight"),
        ("opponent_impact", "opponent_line"),
        ("head_to_head", "head_to_head"),
    ):
        value = facts.get(key)
        if value:
            insights.append({"category": category, "line": str(value), "facts_used": []})

    if not insights:
        insights.append({
            "category": "match_context",
            "line": str(facts.get("what_happened") or "Live match event processed."),
            "facts_used": [],
        })

    return insights[:5]


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

def generate_insights(prompt, allowed_facts, editorial_context: dict | None = None):

    try:
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
            raise ValueError("Every insight failed grounding.")

        return {
            "lead_story": lead_story,
            "insights": grounded_insights,
        }
    except Exception:
        if editorial_context is None:
            raise

        return {
            "lead_story": _fallback_lead_story(editorial_context),
            "insights": _fallback_insights(editorial_context),
        }