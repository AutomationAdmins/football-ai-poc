import json
import os
import re

import google.generativeai as genai

_GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
_client = None


def _get_model():
    global _client
    if _client is None:
        genai.configure(api_key=_GEMINI_KEY)
        _client = genai.GenerativeModel(_MODEL)
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
    model = _get_model()
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text


def _fallback_lead_story(editorial_context: dict) -> str:
    event = editorial_context.get("event", {}) if isinstance(editorial_context, dict) else {}
    facts = editorial_context.get("commentator_facts", {}) if isinstance(editorial_context, dict) else {}
    player_ctx = editorial_context.get("player", {}) if isinstance(editorial_context, dict) else {}
    match_state = editorial_context.get("match_state", {}) if isinstance(editorial_context, dict) else {}
    player_performance = editorial_context.get("player_performance", {}) if isinstance(editorial_context, dict) else {}

    player = event.get("player") or facts.get("player") or "The player"
    team = event.get("team") or facts.get("team") or "the team"
    opponent = event.get("opponent") or facts.get("opponent") or "the opponent"
    minute = event.get("minute") or facts.get("minute") or ""
    score = event.get("score") or facts.get("score") or ""
    event_type = str(event.get("event_type") or "GOAL").upper()

    # Build narrative consequence
    consequence = ""
    
    # Check for milestone/performance narrative
    if player_performance:
        goals_today = player_performance.get("goals_today", 0)
        if goals_today >= 3:
            consequence = f"{player} completes a stunning hat-trick"
        elif goals_today == 2:
            consequence = f"{player} with his second of the match"
    
    # League stakes from commentator facts
    if not consequence:
        for key in ("promotion_stakes", "champions_league_stakes", "title_race", "relegation_stakes"):
            val = facts.get(key)
            if val and isinstance(val, str):
                consequence = val
                break
    
    # Season stats as colour
    if not consequence and player_ctx:
        season_goals = player_ctx.get("season_goals")
        season_assists = player_ctx.get("season_assists")
        if season_goals:
            consequence = f"That's {season_goals} goals this season"
            if season_assists:
                consequence += f" alongside {season_assists} assists"
    
    # Score context narrative
    if not consequence and score:
        parts = score.split("-")
        if len(parts) == 2:
            try:
                home_g, away_g = int(parts[0]), int(parts[1])
                if home_g == away_g:
                    consequence = "the scores are level"
                elif abs(home_g - away_g) >= 3:
                    leader = team if home_g > away_g else opponent
                    consequence = f"{leader} running away with it"
            except ValueError:
                pass

    # Build the lead
    if event_type == "RED_CARD":
        base = f"{player} sees red for {team} against {opponent} at {minute}'. {score}"
        if consequence:
            lead = f"{base} — {consequence}"
        else:
            lead = f"{base} — {team} down to ten men"
    elif event_type == "VAR_DECISION":
        base = f"VAR intervenes in {team} vs {opponent} at {minute}' — {score}"
        if consequence:
            lead = f"{base}. {consequence}"
        else:
            lead = base
    elif event_type == "PENALTY":
        base = f"{player} converts from the spot for {team} against {opponent} — {score} at {minute}'"
        if consequence:
            lead = f"{base}. {consequence}"
        else:
            lead = base
    elif event_type == "OWN_GOAL":
        base = f"Own goal! {player} puts through his own net — {score} at {minute}'"
        if consequence:
            lead = f"{base}. {consequence}"
        else:
            lead = base
    else:
        # GOAL — tell the story
        # Determine goal type from score context
        goal_desc = "scores"
        if score:
            parts = score.split("-")
            if len(parts) == 2:
                try:
                    home_g, away_g = int(parts[0]), int(parts[1])
                    if home_g == away_g:
                        goal_desc = "equalises"
                    elif home_g + away_g == 1:
                        goal_desc = "opens the scoring"
                except ValueError:
                    pass
        
        base = f"{player} {goal_desc} for {team} against {opponent} — {score} at {minute}'"
        if consequence:
            lead = f"{base}. {consequence}"
        else:
            lead = base

    return lead.strip().rstrip(".")  + "."


def _fallback_insights(editorial_context: dict) -> list[dict]:
    facts = editorial_context.get("commentator_facts", {}) if isinstance(editorial_context, dict) else {}
    event = editorial_context.get("event", {}) if isinstance(editorial_context, dict) else {}
    player_ctx = editorial_context.get("player", {}) if isinstance(editorial_context, dict) else {}
    match_state = editorial_context.get("match_state", {}) if isinstance(editorial_context, dict) else {}
    player_performance = editorial_context.get("player_performance", {}) if isinstance(editorial_context, dict) else {}
    insights = []

    player = event.get("player") or facts.get("player") or ""
    team = event.get("team") or facts.get("team") or ""
    
    # Milestone insight
    milestone_text = facts.get("player_highlight")
    if milestone_text:
        insights.append({"category": "milestone", "line": str(milestone_text), "facts_used": []})
    
    # League impact
    for key in ("promotion_stakes", "champions_league_stakes", "title_race", "relegation_stakes"):
        val = facts.get(key)
        if val and isinstance(val, str):
            insights.append({"category": "league_impact", "line": val, "facts_used": []})
            break
    
    # Player stat — build a natural sentence
    if player and player_ctx:
        season_goals = player_ctx.get("season_goals")
        season_assists = player_ctx.get("season_assists")
        goals_today = player_performance.get("goals_today", 0) if player_performance else 0
        
        parts = []
        if goals_today > 0:
            parts.append(f"{player} now has {goals_today} goal{'s' if goals_today > 1 else ''} in this match")
        if season_goals is not None:
            stat = f"{season_goals} goals"
            if season_assists is not None:
                stat += f" and {season_assists} assists"
            parts.append(f"{stat} this season")
        
        if parts:
            insights.append({"category": "player_stat", "line": " — ".join(parts), "facts_used": []})
    
    # Team stat
    team_highlight = facts.get("team_highlight")
    if team_highlight:
        insights.append({"category": "team_stat", "line": str(team_highlight), "facts_used": []})
    
    # Head to head
    h2h = facts.get("head_to_head")
    if h2h:
        insights.append({"category": "head_to_head", "line": str(h2h), "facts_used": []})
    
    # Opponent impact
    opp = facts.get("opponent_line")
    if opp:
        insights.append({"category": "opponent_impact", "line": str(opp), "facts_used": []})

    # Match context - what's happening in the game right now
    what_happened = facts.get("what_happened")
    if what_happened:
        insights.append({"category": "match_context", "line": str(what_happened), "facts_used": []})

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