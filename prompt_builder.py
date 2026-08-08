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


def build_insight_prompt(editorial_context: dict, match_history: list[dict] | None = None):
    """
    Prompt for generating commentator-ready lead story and stat pack.
    match_history is Layer 2 — in-match events before this one.
    """

    cleaned = _clean_context(editorial_context)

    # Surface key signals to guide the LLM
    player = cleaned.get("player", {})
    commentator = cleaned.get("commentator_facts", {})
    event_info = cleaned.get("event", {})
    event_type = event_info.get("event_type", "GOAL").upper()

    has_milestone = bool(
        player.get("next_milestone")
        or player.get("notes")
        or player.get("goals_to_next_milestone") is not None
    )
    has_head_to_head = bool(commentator.get("head_to_head"))
    has_streak = bool(
        player.get("consecutive_scoring_matches")
        or player.get("consecutive_goal_involvements")
    )

    # Build conditional instruction blocks
    milestone_rule = ""
    if has_milestone:
        milestone_rule = (
            "\nMILESTONE RULE (MANDATORY): The player.notes or player.next_milestone field contains a historic milestone. "
            "You MUST generate a 'milestone' insight. State the player's name, their current tally, the target, and why it is significant. "
            "Example: \"Haaland on 99 Premier League goals — 1 away from 100, the fastest player in history to reach the landmark.\""
        )

    h2h_rule = ""
    if has_head_to_head:
        h2h_rule = (
            "\nHEAD-TO-HEAD RULE (MANDATORY): commentator_facts.head_to_head contains fixture head-to-head goal data. "
            "You MUST generate a 'head_to_head' insight using those exact numbers. "
            "Example: \"Arsenal 9, Chelsea 8 — head-to-head goals in this fixture.\""
        )

    streak_rule = ""
    if has_streak:
        streak_rule = (
            "\nSTREAK RULE: The player has a consecutive scoring or involvement streak. "
            "You MUST include this streak stat in BOTH the match_context line AND the player_stat line."
        )

    if event_type == "RED_CARD":
        lead_format = '"[Full Player Name] is sent off for [Team] against [Opponent] at [Minute]\'. [Score]. [One key consequence OR one standout stat]."'
        match_context_format = '"[Player] is sent off for [Team] against [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = ""
    elif event_type == "HALF_TIME":
        lead_format = '"Half-time in [Team] vs [Opponent] — [Score] at [Minute]\'. [One key consequence OR one standout stat]."'
        match_context_format = '"Half-time in [Team] vs [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = ""
    elif event_type == "FULL_TIME":
        lead_format = '"Full-time in [Team] vs [Opponent] — [Score] at [Minute]\'. [One key consequence OR one standout stat]."'
        match_context_format = '"Full-time in [Team] vs [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = ""
    elif event_type == "VAR_DECISION":
        lead_format = '"VAR decision in [Team] vs [Opponent] at [Minute]\' — [Score]. [One key consequence OR one standout stat]."'
        match_context_format = '"VAR decision in [Team] vs [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = ""
    elif event_type == "PENALTY":
        lead_format = '"[Full Player Name] scores a penalty for [Team] against [Opponent] — [Score] at [Minute]\'. [One key consequence OR one standout stat]."'
        match_context_format = '"[Player] scores a penalty for [Team] against [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = ""
    elif event_type == "OWN_GOAL":
        lead_format = '"[Full Player Name] scores an own goal for [Team] against [Opponent] — [Score] at [Minute]\'. [One key consequence OR one standout stat]."'
        match_context_format = '"[Player] scores an own goal for [Team] against [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = ""
    else:
        lead_format = '"[Full Player Name] scores [goal type] for [Team] against [Opponent] — [Score] at [Minute]\'. [One key consequence OR one standout stat]."'
        match_context_format = '"[Player] scores/equalises for [Team] against [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = '- Goal type must be specific: "the equaliser", "the go-ahead goal", "a penalty", "his Nth goal of the season", "his 100th Premier League goal"\n   '

    prompt = f"""
You are a broadcast football statistician preparing lines for live TV commentators.

Generate a LEAD STORY plus 3 to 5 supporting insights for this event.

Use the commentator_facts block as your primary source for key numbers and stakes.
Use player, team, fixture, and league sections for supporting detail.

Rules

1. LEAD STORY — This is the commentator's opening line on live television. It must be punchy, data-rich, and worth reading aloud.
   MANDATORY FORMAT: {lead_format}
   {goal_type_rule}- Always include the score AND minute — never omit either
   - The consequence MUST state the exact season impact (e.g. "Leeds head for automatic promotion", "Arsenal move to within one win of the title", "Chelsea retain their Champions League place")
   - If a milestone exists, weave it into the lead instead of the consequence
   - Max 40 words. No vague phrases like "big moment" or "crucial goal" — use facts
   - Examples of GOOD leads:
     * "Summerville scores the equaliser for Leeds against Sunderland — 1-1 at 87'. His 24th Championship goal — Leeds head for automatic promotion after 3 years away."
     * "Haaland scores his 100th Premier League goal for Manchester City against Liverpool — 3-1 at 87'. The fastest player in history to reach the landmark."
     * "Palmer scores the 90th-minute equaliser for Chelsea against Arsenal — 1-1. Chelsea hold onto their Champions League place — Newcastle United stay 5th."
     * "Van Dijk is sent off for Liverpool against Manchester United at 87'. 1-1. Liverpool's title hopes suffer a massive blow."
   - Examples of BAD leads (DO NOT write these):
     * "Summerville scores for Leeds — promotion." ❌ (no score, no minute, no data)
     * "Haaland goal — City win title." ❌ (vague, no numbers)
     * "Big moment for Arsenal as Saka scores." ❌ (no score, no minute, no consequence)
2. Each insight line = one focused stat or fact. Max 20 words. One key number per line where possible.
3. Do NOT repeat the editorial ranking reason or restate the lead story in insights.
4. Prioritise insights in this order:
   (a) milestone (if present — MANDATORY)
   (b) league_impact
   (c) live match moment (match_context)
   (d) player record
   (e) team form
   (f) head_to_head (if present — MANDATORY)
   (g) opponent impact
5. Use ONLY facts from Context. Never invent numbers or names.
6. Write in present tense, broadcast-ready English — short, punchy, on-air readable.
7. Every number in your output must appear in the supplied Context.
8. Pull key numbers from commentator_facts, player, and team sections — do not write vague lines without stats.
{milestone_rule}{h2h_rule}{streak_rule}

Data Specificity Rules — CRITICAL:

- match_context MUST follow: {match_context_format} Then append the player's consecutive streak if available, or their season goal tally.
- player_stat MUST name the player and include: goals, assists (if available), own_goals (if available), and the consecutive streak (if available). Example: "Saka has 23 goals and 14 assists this season — 7 consecutive goal involvements."
- team_stat MUST name the team and include at least two numbers (points, position, streak, goal difference, or home record).
- league_impact MUST name the team and state the exact consequence clearly.
- opponent_impact MUST name the opponent with at least one number (points, position, or consequence).
- milestone MUST state: player name, current tally, exact target, and why it is significant.
- head_to_head MUST use the exact numbers from commentator_facts.head_to_head.

Categories for insights (use exactly one per insight):
- league_impact
- match_context
- player_stat
- team_stat
- opponent_impact
- head_to_head
- milestone

Return ONLY JSON. Do NOT include a facts_used field.

Example (with milestone, streak, and head-to-head all present)

{{
    "lead_story": "Haaland scores his 100th Premier League goal for Man City against Liverpool — 3-1 at 87'. The fastest player in history to reach the landmark — City close in on the title.",
    "insights": [
        {{
            "category": "milestone",
            "line": "Haaland reaches 100 Premier League goals — the fastest player in history to the landmark, in just 35 appearances."
        }},
        {{
            "category": "league_impact",
            "line": "Manchester City win the title outright today regardless of Arsenal's result."
        }},
        {{
            "category": "match_context",
            "line": "Haaland scores for Man City against Liverpool — 3-1 at 87', his 6th consecutive scoring match."
        }},
        {{
            "category": "player_stat",
            "line": "Haaland has 35 goals and 5 assists this season — 6 consecutive scoring matches and 10 career goals vs Liverpool."
        }},
        {{
            "category": "team_stat",
            "line": "Man City on 75 points, 1st in the Premier League, +44 goal difference."
        }},
        {{
            "category": "head_to_head",
            "line": "Man City 11, Liverpool 8 — head-to-head goals in this fixture."
        }},
        {{
            "category": "opponent_impact",
            "line": "Liverpool have Champions League secured — but a win here gifts Arsenal the title."
        }}
    ]
}}

Context

{json.dumps(cleaned, indent=2)}

Match History (events in this match before the current event)

{json.dumps(match_history or [], indent=2)}
"""

    return prompt
