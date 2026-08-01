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
6. For each event include a confidence score (integer 0–100) representing how clear this editorial decision was:
   - 90–100 = one event is obviously more important, no real contest
   - 70–89  = clear preference, but the other event has some merit
   - 50–69  = genuinely close — both events have strong editorial case
   - Below 50 = near coin-flip, editorial judgement call

Return ONLY JSON.

Do NOT use external football knowledge.

Return ONLY JSON.

Example

{{
    "ranking":[
        {{
            "event_index":1,
            "priority":"Critical",
            "confidence":72,
            "reason":"Promotion race changed — equaliser keeps Leeds in automatic promotion. Close call as the milestone goal has high audience draw."
        }},
        {{
            "event_index":0,
            "priority":"High",
            "confidence":72,
            "reason":"Historic player milestone but does not change the league table directly."
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

Data Specificity Rules — CRITICAL:

- match_context insight MUST follow this exact format: "[Player] scores/equalises for [Team] against [Opponent] — [Score] at [Minute]'." Then append one additional stat. Always use commentator_facts.score and commentator_facts.minute.
- player_stat insight MUST name the player and include at least one specific number. Never say "23 goals this season" — always say "[Name] has 23 goals this season."
- team_stat insight MUST name the team and include at least two numbers (e.g. points, position, streak, goal difference, home record).
- season_stakes insight MUST name the team and state the exact consequence clearly.
- opponent_impact insight MUST name the opponent with at least one number or specific consequence.
- milestone insight MUST state the player name, current tally, and the exact target.
- Every insight that references a live moment MUST include the score and minute in the format "— [Score] at [Minute]'".

Categories for insights (use exactly one per insight):
- season_stakes
- match_context
- player_stat
- team_stat
- opponent_impact
- head_to_head
- milestone

Return ONLY JSON. Do NOT include a facts_used field.

Example

{{
    "lead_story": "Summerville equalises in the 87th minute — Leeds are one result away from the Premier League.",
    "insights": [
        {{
            "category": "match_context",
            "line": "Summerville scores the equaliser for Leeds against Sunderland — 1-1 at 87', his 5th goal in as many games."
        }},
        {{
            "category": "player_stat",
            "line": "Summerville has 23 Championship goals this season and 4 career goals against Sunderland."
        }},
        {{
            "category": "team_stat",
            "line": "Leeds on 87 points, 1st in the Championship, unbeaten in 21 home games."
        }},
        {{
            "category": "season_stakes",
            "line": "Leeds are promoted automatically with a win or draw today — 3 seasons outside the Premier League."
        }},
        {{
            "category": "opponent_impact",
            "line": "Sunderland must win to secure a higher playoff seeding — currently 3rd with 79 points."
        }}
    ]
}}

Context

{json.dumps(cleaned, indent=2)}
"""

    return prompt

