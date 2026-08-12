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
    """Generate a broadcaster-quality lead story as fallback when Gemini fails."""
    import random as _rng
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
    xg = event.get("xG")
    build_up = event.get("build_up_players") or []
    pressure = event.get("pressure_index")

    # Determine goal context
    goals_today = (player_performance or {}).get("goals_today", 0)
    red_cards = (match_state or {}).get("red_cards", [])
    min_str = f"{minute}'" if minute else ""

    # Consequence / colour
    consequence = ""
    for key in ("promotion_stakes", "champions_league_stakes", "title_race", "relegation_stakes"):
        val = facts.get(key)
        if val and isinstance(val, str):
            consequence = val
            break
    if not consequence and player_ctx:
        sg = player_ctx.get("season_goals")
        sa = player_ctx.get("season_assists")
        if sg:
            consequence = f"That's {sg} goals this season"
            if sa:
                consequence += f" alongside {sa} assists"

    if event_type == "GOAL":
        # Determine goal type
        goal_type = ""
        if score and "-" in score:
            try:
                h, a = map(int, score.split("-"))
                if h == a:
                    goal_type = "equaliser"
                elif h + a == 1:
                    goal_type = "opener"
                else:
                    goal_type = "go_ahead_goal"
            except ValueError:
                pass

        # Build-up description
        buildup = ""
        if len(build_up) >= 2:
            buildup = _rng.choice([
                f"{build_up[0]} and {build_up[1]} combine brilliantly",
                f"Lovely work from {build_up[0]} and {build_up[1]}",
            ])
        elif len(build_up) == 1:
            buildup = f"{build_up[0]} with the perfect pass"

        # Shot quality
        chance = ""
        if xg is not None:
            if xg >= 0.70:
                chance = "a clinical finish from close range"
            elif xg >= 0.35:
                chance = "a composed strike from a good position"
            elif xg >= 0.15:
                chance = "a fine effort against the odds"
            else:
                chance = "an absolute screamer from nowhere"

        # Opener shout
        if goals_today >= 3:
            shout = f"GOAL! THE HAT-TRICK! {player.upper()} HAS THREE!"
        elif goals_today == 2:
            shout = _rng.choice([f"GOAL! HE'S DONE IT AGAIN! {player.upper()} WITH HIS SECOND!", f"GOAL! THE BRACE FOR {player.upper()}!"])
        elif goal_type == "equaliser":
            shout = _rng.choice([f"GOAL! {team.upper()} ARE LEVEL!", f"GOAL! THE EQUALISER FROM {player.upper()}!"])
        elif goal_type == "opener":
            shout = _rng.choice([f"GOAL! {player.upper()} OPENS THE SCORING!", f"GOAL! FIRST BLOOD FOR {team.upper()}!"])
        elif (minute or 0) >= 85:
            shout = _rng.choice([f"GOAL! LATE DRAMA! {player.upper()} STRIKES!", f"GOAL! IN THE DYING MINUTES! {player.upper()}!"])
        elif xg is not None and xg < 0.15:
            shout = _rng.choice([f"GOAL! WHAT A STRIKE! {player.upper()} FROM NOWHERE!", f"GOAL! SENSATIONAL FROM {player.upper()}!"])
        else:
            shout = _rng.choice([f"GOAL! {player.upper()} FOR {team.upper()}!", f"GOAL! OH WHAT A FINISH FROM {player.upper()}!"])

        # Assemble
        parts = [shout]
        if buildup and chance:
            parts.append(f"{buildup} — {chance}.")
        elif buildup:
            parts.append(f"{buildup}, and {player} finishes it off!")
        elif chance:
            parts.append(f"{chance[0].upper() + chance[1:]}.")
        parts.append(f"{score} at {min_str}.")
        if consequence:
            parts.append(consequence + ".")
        return " ".join(parts)

    elif event_type == "RED_CARD":
        mins_left = 90 - (minute or 0)
        if pressure and pressure >= 80:
            shout = _rng.choice([f"RED CARD! OFF HE GOES!", f"RED CARD! THE REFEREE HAS NO CHOICE!"])
            lead = f"{shout} {player.upper()} — a desperate, reckless challenge! {team} are down to ten men at {min_str}. {score}."
        else:
            shout = _rng.choice([f"RED CARD! {player.upper()} IS SENT OFF!", f"RED CARD! OH DEAR!"])
            lead = f"{shout} {team} with ten men against {opponent} at {min_str}. {score}."
        if mins_left > 0:
            lead += f" {mins_left} long minutes to survive."
        return lead

    elif event_type == "PENALTY":
        shout = _rng.choice(["PENALTY CONVERTED!", "HE SENDS THE KEEPER THE WRONG WAY!"])
        lead = f"{shout} {player.upper()} for {team}! {score} at {min_str} against {opponent}!"
        if consequence:
            lead += f" {consequence}."
        return lead

    elif event_type == "HALF_TIME":
        return f"HALF-TIME! {team} {score} {opponent} at the break. {consequence + '.' if consequence else ''}"

    elif event_type == "FULL_TIME":
        return f"FULL-TIME! {team} {score} {opponent}! {consequence + '.' if consequence else ''}"

    else:
        return f"{event_type.replace('_', ' ').upper()}! {team} {score} {opponent} at {min_str}. {consequence + '.' if consequence else ''}"


def _fallback_insights(editorial_context: dict) -> list[dict]:
    """Generate broadcaster-quality narrative insights as fallback."""
    import random as _rng
    facts = editorial_context.get("commentator_facts", {}) if isinstance(editorial_context, dict) else {}
    event = editorial_context.get("event", {}) if isinstance(editorial_context, dict) else {}
    player_ctx = editorial_context.get("player", {}) if isinstance(editorial_context, dict) else {}
    match_state = editorial_context.get("match_state", {}) if isinstance(editorial_context, dict) else {}
    player_performance = editorial_context.get("player_performance", {}) if isinstance(editorial_context, dict) else {}
    team_ctx = editorial_context.get("team", {}) if isinstance(editorial_context, dict) else {}
    insights = []

    player = event.get("player") or facts.get("player") or ""
    team = event.get("team") or facts.get("team") or ""
    opponent = event.get("opponent") or facts.get("opponent") or ""
    minute = event.get("minute") or ""
    score = event.get("score") or ""
    xg = event.get("xG")
    build_up = event.get("build_up_players") or []
    goals_today = (player_performance or {}).get("goals_today", 0)

    # --- MILESTONE ---
    if goals_today >= 3:
        sg = player_ctx.get("season_goals", "")
        insights.append({"category": "milestone",
            "line": f"THE HAT-TRICK! {player.upper()} is on fire — three goals today" + (f", {sg} for the season! Unstoppable!" if sg else "! What a performance!"),
            "facts_used": []})
    elif goals_today == 2:
        sg = player_ctx.get("season_goals", "")
        insights.append({"category": "milestone",
            "line": f"THE BRACE! {player} with two today" + (f" — that's {sg} for the season and he shows no signs of slowing down!" if sg else " — a devastating impact on this game!"),
            "facts_used": []})
    else:
        milestone_text = facts.get("player_highlight")
        if milestone_text:
            # Convert semicolon dumps into narrative
            parts = [p.strip() for p in str(milestone_text).split(";") if p.strip()]
            if len(parts) >= 2:
                insights.append({"category": "milestone",
                    "line": f"WHAT A RECORD FOR {player.upper()}! {parts[0]} — {parts[1]}." + (f" {parts[2]}." if len(parts) > 2 else ""),
                    "facts_used": []})
            elif parts:
                insights.append({"category": "milestone", "line": f"MILESTONE! {parts[0]} for {player}!", "facts_used": []})

    # --- LEAGUE IMPACT ---
    for key in ("promotion_stakes", "champions_league_stakes", "title_race", "relegation_stakes"):
        val = facts.get(key)
        if val and isinstance(val, str):
            insights.append({"category": "league_impact", "line": f"THE STAKES! {val}", "facts_used": []})
            break

    # --- PLAYER STAT (narrative, not stat dump) ---
    if player and player_ctx:
        season_goals = player_ctx.get("season_goals")
        season_assists = player_ctx.get("season_assists")
        streak = player_ctx.get("consecutive_scoring_matches") or player_ctx.get("consecutive_goal_involvements")

        if season_goals is not None:
            narrative = f"WHAT A SEASON! {player} now has {season_goals} goals"
            if season_assists:
                narrative += f" and {season_assists} assists"
            narrative += " this campaign"
            if streak:
                narrative += f" — scoring in {streak} consecutive matches!"
            else:
                narrative += "!"
            insights.append({"category": "player_stat", "line": narrative, "facts_used": []})

    # --- MATCH CONTEXT: xG + build-up as narrative ---
    if xg is not None:
        if xg >= 0.70:
            xg_line = f"xG {xg:.2f} — a clear-cut chance and {player} was never going to miss from there!"
        elif xg >= 0.35:
            xg_line = f"xG {xg:.2f} — a good opportunity well taken by {player}!"
        elif xg >= 0.10:
            xg_line = f"xG just {xg:.2f} — {player} had no right to score that! What a strike!"
        else:
            xg_line = f"xG only {xg:.2f} — an outrageous effort! That should NOT have gone in!"
        if build_up:
            xg_line += f" Brilliant build-up from {' and '.join(build_up)}."
        insights.append({"category": "match_context", "line": xg_line, "facts_used": []})
    elif build_up:
        insights.append({"category": "match_context",
            "line": f"What a move! {' and '.join(build_up)} tore the defence apart to create the chance for {player}!",
            "facts_used": []})

    # --- TEAM STAT ---
    if team_ctx:
        points = team_ctx.get("points")
        position = team_ctx.get("position") or team_ctx.get("league_position")
        gd = team_ctx.get("goal_difference")
        if points and position:
            pos_int = int(position) if str(position).isdigit() else None
            suffix = "th" if pos_int and 11 <= pos_int <= 13 else {1: "st", 2: "nd", 3: "rd"}.get((pos_int or 0) % 10, "th") if pos_int else ""
            gd_str = f" with a goal difference of {gd:+d}" if isinstance(gd, int) else ""
            insights.append({"category": "team_stat",
                "line": f"THE TABLE! {team} sit {position}{suffix} on {points} points{gd_str} — every goal matters in this title race!",
                "facts_used": []})

    # --- HEAD TO HEAD ---
    h2h = facts.get("head_to_head")
    if h2h:
        insights.append({"category": "head_to_head",
            "line": f"THE RIVALRY! {h2h} — and this fixture never disappoints!",
            "facts_used": []})

    # --- MATCH CONTEXT fallback ---
    what_happened = facts.get("what_happened")
    if what_happened and not any(i["category"] == "match_context" for i in insights):
        insights.append({"category": "match_context", "line": str(what_happened), "facts_used": []})

    if not insights:
        insights.append({
            "category": "match_context",
            "line": f"{minute}' — {team} {score} {opponent}. The game continues!",
            "facts_used": [],
        })

    # Event-type category filter — only return relevant categories
    evt = str(event.get("event_type", "")).upper()
    _allowed = {
        "GOAL": {"milestone", "match_context", "player_stat"},
        "PENALTY": {"milestone", "match_context", "player_stat"},
        "RED_CARD": {"match_context", "milestone"},
        "HALF_TIME": {"match_context", "tactical", "head_to_head", "milestone"},
        "FULL_TIME": {"match_context", "tactical", "milestone", "league_impact", "player_stat"},
    }
    _cats = _allowed.get(evt, set())
    if _cats:
        insights = [i for i in insights if i.get("category") in _cats]

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

        # --- QUALITY GATE: reject bland Gemini output ---
        # Lead must start with a shout word for GOAL/RED_CARD/PENALTY events
        event_info = (editorial_context or {}).get("event", {})
        evt_type = str(event_info.get("event_type", "")).upper() if event_info else ""
        shout_required = evt_type in ("GOAL", "RED_CARD", "PENALTY", "HALF_TIME", "FULL_TIME")
        shout_words = ("GOAL!", "RED CARD!", "PENALTY!", "HALF-TIME!", "FULL-TIME!", "VAR!", "OH", "WOW", "YES", "WHAT", "DRAMA", "INCREDIBLE", "UNBELIEVABLE")
        if shout_required and not any(lead_story.upper().startswith(w) for w in shout_words):
            raise ValueError(f"Lead story lacks broadcaster voice: '{lead_story[:50]}...'")

        # Reformat any insight lines that are semicolon stat dumps
        for i, insight in enumerate(grounded_insights):
            line = insight["line"]
            if line.count(";") >= 2:
                # Convert "stat1; stat2; stat3" into narrative
                parts = [p.strip() for p in line.split(";") if p.strip()]
                player_name = event_info.get("player", "") if event_info else ""
                if parts:
                    grounded_insights[i]["line"] = f"THE STATS! {parts[0]} — {' — '.join(parts[1:3])}."

        return {
            "lead_story": lead_story,
            "insights": grounded_insights,
        }
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"AI Generation failed: {e}")
        logger.error(traceback.format_exc())
        if editorial_context is None:
            raise

        return {
            "lead_story": _fallback_lead_story(editorial_context),
            "insights": _fallback_insights(editorial_context),
        }