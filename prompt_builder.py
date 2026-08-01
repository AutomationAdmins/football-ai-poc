import json


def _clean_context(context: dict) -> dict:
    """
    Removes None values so the LLM receives only useful facts.
    """

    if isinstance(context, dict):

        cleaned = {}

        for key, value in context.items():

            if value is None:
                continue

            if isinstance(value, dict):
                nested = _clean_context(value)

                if nested:
                    cleaned[key] = nested

            elif isinstance(value, list):
                cleaned[key] = value

            else:
                cleaned[key] = value

        return cleaned

    return context


def build_editorial_prompt(editorial_contexts: list[dict]) -> str:
    """
    Prompt for comparing simultaneous events.
    """

    cleaned_events = [
        _clean_context(event)
        for event in editorial_contexts
    ]

    prompt = f"""
You are the Senior Editorial Producer for Soccer Saturday.

Several football events have occurred simultaneously.

Your responsibility is NOT to generate statistics.

Your responsibility is to determine which event should be shown first on live television.

Your decision must be based ONLY on the supplied facts.

Never invent facts.

Never infer facts.

Never assume anything.

When comparing simultaneous events, think like the Senior Producer of a live Soccer Saturday broadcast.

Editorial Principles

1. Prioritise events that CHANGE the competitive outcome.

Examples include:

- Equalising goals
- Winning goals
- Goals that change league position
- Goals affecting promotion
- Goals affecting relegation
- Goals affecting qualification
- Goals affecting the title race

2. A routine goal extending an already comfortable lead is usually LESS important than a goal that changes the season outcome.

Example:

A fourth goal in a 4-0 match is usually less editorially significant than an equaliser that keeps a team on course for promotion.

3. Do NOT favour famous clubs automatically.

Manchester City, Manchester United, Liverpool or Arsenal should not receive higher priority solely because of club size.

4. Historical milestones should increase priority only when they are exceptional and supported by the supplied facts.

5. Base every decision ONLY on the supplied context.

Return ONLY JSON.

Do NOT use external football knowledge.

Return ONLY JSON.

Example

{{
    "ranking":[
        {{
            "event_index":1,
            "priority":"Critical",
            "reason":"Promotion race changed."
        }},
        {{
            "event_index":0,
            "priority":"High",
            "reason":"Historic player milestone."
        }}
    ]
}}

Editorial Context

{json.dumps(cleaned_events, indent=2)}
"""

    return prompt


def build_insight_prompt(editorial_context: dict):
    """
    Prompt for generating commentator-ready lead story and stat pack.
    """

    cleaned = _clean_context(editorial_context)

    prompt = f"""
You are a broadcast football statistician preparing lines for live TV commentators.

Generate a LEAD STORY plus 3 to 5 supporting insights for this event.

Use the commentator_facts block as your primary source for key numbers and stakes.
Use player, team, fixture, and league sections for supporting detail.

Rules

1. Lead story = one sentence, max 25 words. Name the scorer and team. State WHAT happened AND the main season stake (title, promotion, relegation, or qualification).
2. Each insight line = one focused stat or fact. Max 20 words. One key number per line where possible.
3. Do NOT repeat the editorial ranking reason or restate the lead story in insights.
4. Prioritise insights in this order:
   (a) season stakes
   (b) live match moment
   (c) player record
   (d) team form
   (e) opponent impact
5. Use ONLY facts from Context. Never invent numbers or names.
6. Write in present tense, broadcast-ready English — short, punchy, on-air readable.
7. Every number in your output must appear in the supplied Context.
8. Pull key numbers from commentator_facts, player, and team sections — do not write vague lines without stats.

Categories for insights (use exactly one per insight):
- season_stakes
- match_context
- player_stat
- team_stat
- opponent_impact
- head_to_head
- milestone

Return ONLY JSON.

Example

{{
    "lead_story": "Summerville equalises in the 87th minute — Leeds are one result away from the Premier League.",
    "insights": [
        {{
            "category": "player_stat",
            "line": "5 goals in 5 consecutive matches; 4 career goals against Sunderland.",
            "facts_used": ["consecutive_scoring_matches", "goals_vs_sunderland_career"]
        }},
        {{
            "category": "team_stat",
            "line": "Leeds on 87 points with a 5-game win streak and 21 home games unbeaten.",
            "facts_used": ["points", "winning_streak", "home_unbeaten"]
        }},
        {{
            "category": "season_stakes",
            "line": "A draw confirms automatic promotion after 3 seasons outside the top flight.",
            "facts_used": ["promotion_stakes", "years_out_of_premier_league"]
        }},
        {{
            "category": "opponent_impact",
            "line": "Sunderland need a win to strengthen their playoff seeding.",
            "facts_used": ["opponent_line"]
        }}
    ]
}}

Context

{json.dumps(cleaned, indent=2)}
"""

    return prompt
