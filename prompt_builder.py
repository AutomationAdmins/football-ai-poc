import json
from datetime import datetime


def _json_safe(obj):
    """Convert non-serializable types (e.g. Firestore timestamps) to strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


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
    
    # Extract match state and anti-repetition data
    match_state = cleaned.get("match_state", {})
    player_performance = cleaned.get("player_performance", {})
    used_insights = cleaned.get("used_insights", [])

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
    
    # Add hat-trick/brace detection from match state
    if player_performance:
        if player_performance.get("is_hat_trick"):
            milestone_rule = (
                "\nHAT-TRICK DETECTED (MANDATORY): The player has scored 3+ goals in this match. "
                f"You MUST mention 'HAT-TRICK' or 'completes his hat-trick' in the lead story. "
                f"Player has scored {player_performance.get('goals_today')} goals today. {milestone_rule}"
            )
        elif player_performance.get("is_brace"):
            milestone_rule = (
                "\nBRACE DETECTED: The player has scored 2 goals in this match. "
                f"Consider mentioning 'his second goal of the match' if contextually relevant. {milestone_rule}"
            )

    
    # Anti-repetition section
    anti_repetition_rule = ""
    if used_insights:
        anti_repetition_rule = f"""
CRITICAL ANTI-REPETITION RULE:
The following insight lines have ALREADY been shown to viewers in earlier events.
DO NOT repeat these exact phrases or very similar variations:

{json.dumps(used_insights[:15], indent=2)}

Focus on NEW information:
- What changed SINCE the last event (e.g., score change, red card impact)
- Player performance TODAY (goals scored in this match: {player_performance.get('goals_today', 0) if player_performance else 0})
- Match narrative shifts (comeback, collapse, dominance)

If a fact was already shown, find a NEW angle or skip it entirely.
"""
    
    # Match state context
    match_state_summary = ""
    if match_state:
        match_state_summary = f"""
LIVE MATCH STATE (use this to provide fresh context):
- Goals by players today: {dict(match_state.get('goals_by_player', {}))}
- Current minute: {match_state.get('current_minute', 0)}'
- Score progression: {match_state.get('score_progression', [])}
- Red cards: {match_state.get('red_cards', [])}

Use this to describe the CURRENT match situation, not just season-long stats.
"""
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
        lead_format = '"[Player] sees red for [Team] against [Opponent] at [Minute]\'. [Score] — [narrative consequence: what this means for the match/team/league]."'
        match_context_format = '"[Player] is sent off — [Team] down to ten men against [Opponent] at [Minute]\', [Score]."'
        goal_type_rule = ""
    elif event_type == "HALF_TIME":
        lead_format = '"Half-time in [Team] vs [Opponent] — [Score] at [Minute]\'. [One key narrative: who\'s on top and why]."'
        match_context_format = '"Half-time — [Score] between [Team] and [Opponent]."'
        goal_type_rule = ""
    elif event_type == "FULL_TIME":
        lead_format = '"Full-time — [Team] [Score] [Opponent]. [Narrative: star performer, key moment, or league impact]."'
        match_context_format = '"Full-time — [Team] [Score] [Opponent]."'
        goal_type_rule = ""
    elif event_type == "VAR_DECISION":
        lead_format = '"VAR intervenes in [Team] vs [Opponent] at [Minute]\' — [Score]. [What was the decision and its impact]."'
        match_context_format = '"VAR decision at [Minute]\' in [Team] vs [Opponent] — [Score]."'
        goal_type_rule = ""
    elif event_type == "PENALTY":
        lead_format = '"[Player] converts from the spot for [Team] against [Opponent] — [Score] at [Minute]\'. [Consequence or stat]."'
        match_context_format = '"[Player] scores a penalty for [Team] against [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = ""
    elif event_type == "OWN_GOAL":
        lead_format = '"Own goal! [Player] puts through his own net — [Team] [Score] [Opponent] at [Minute]\'. [Impact]."'
        match_context_format = '"Own goal from [Player] — [Score] at [Minute]\'."'
        goal_type_rule = ""
    else:
        lead_format = '"[Player] [goal verb: equalises/opens the scoring/restores the lead/scores] for [Team] against [Opponent] — [Score] at [Minute]\'. [Consequence: season tally, hat-trick, league impact]."'
        match_context_format = '"[Player] scores for [Team] against [Opponent] — [Score] at [Minute]\'."'
        goal_type_rule = '- Goal verb must reflect match context: "equalises", "opens the scoring", "restores the lead", "doubles the advantage", "completes his hat-trick", "pulls one back"\n   '

    prompt = f"""
You are a Sky Sports Soccer Saturday live commentator AND broadcast statistician.

Your job is to write two things for every event:
1. A LIVE COMMENTARY LINE — exactly as a commentator would shout it on air.
2. STAT OVERLAY CARDS — specific grounded facts a producer would put on screen.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART 1 — LIVE COMMENTARY (lead_story)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Write this as if you are shouting it live on Sky Sports Soccer Saturday.

MANDATORY FORMAT: {lead_format}

Voice and tone rules:
- GOALS must open with "GOAL!" in capitals — e.g. "GOAL! BUKAYO SAKA STRIKES FOR ARSENAL!"
- RED CARDS must open with "RED CARD!" — e.g. "RED CARD! REECE JAMES IS OFF!"
- PENALTIES must open with "PENALTY!" — e.g. "PENALTY TO ARSENAL!"
- VAR must open with "VAR INTERVENES!" — e.g. "VAR INTERVENES AT THE EMIRATES!"
- HALF_TIME must open with "HALF-TIME!" — e.g. "HALF-TIME AT THE EMIRATES!"
- FULL_TIME must open with "FULL-TIME!" — e.g. "FULL-TIME! ARSENAL WIN!"
- After the shout, describe WHAT HAPPENED in one vivid sentence — how the goal was scored, the assist, the drama
- Then add the CONSEQUENCE — league impact, milestone, or season stakes

{goal_type_rule}

Examples of PERFECT live commentary leads:
  GOAL → "GOAL! ALEXANDER ISAK STRIKES EARLY! Gordon cuts open the backline, and Isak coolly slots it past the keeper! His 32nd Premier League goal at St. James' Park — making him one of the most efficient home scorers in Tyneside history!"
  GOAL → "GOAL! ANTHONY GORDON EQUALISES FOR TEN-MAN NEWCASTLE! ST. JAMES' PARK GOES ABSOLUTELY WILD! Newcastle have now scored in 14 consecutive home games against Big Six opposition!"
  GOAL → "GOAL! MOHAMED SALAH EQUALISES FOR LIVERPOOL! Mac Allister slips him through, and Salah buries it into the far corner! RECORD EXTENDED — Salah extends his all-time Premier League record for Matchweek 1 goals to 11!"
  RED CARD → "RED CARD! FABIAN SCHÄR IS SENT OFF FOR A LAST-MAN CHALLENGE ON DARWIN NÚÑEZ! Newcastle are down to 10 men with 17 minutes remaining!"
  PENALTY → "PENALTY SAVED BY NICK POPE! Pope guesses right and denies Salah from the spot! The 10 men of Newcastle are still alive in this match!"
  HALF_TIME → "HALF-TIME AT ST. JAMES' PARK! An electric first 45 minutes ends 1-1 thanks to strikes from Alexander Isak and Mohamed Salah."
  FULL_TIME → "FULL-TIME! A ten-man Newcastle United salvage a dramatic 2-2 draw against Liverpool in another classic St. James' Park thriller!"

BAD examples (NEVER write these):
  ❌ "Saka scores for Arsenal." (no drama, no shout, no consequence)
  ❌ "Big moment for Leeds as Summerville scores." (vague, no stats)
  ❌ "Goal — 1-0." (no player, no context)

Max 50 words. Always include score AND minute.
{milestone_rule}{h2h_rule}{streak_rule}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART 2 — STAT OVERLAY CARDS (insights)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Generate 3–5 stat overlay cards. Each card is a single stat line a producer would put on screen during the broadcast.

Each card must:
- Be specific, grounded in the supplied Context — NO invented numbers
- Read like a Sky Sports ticker or overlay graphic — punchy, factual, max 20 words
- Cover a DIFFERENT angle from the lead story
- NOT repeat the lead story content

Stat overlay card format examples (these are the GOLD STANDARD):
  milestone   → "Isak has now scored 32 Premier League goals at St. James' Park — one of the most efficient home scorers since Les Ferdinand."
  milestone   → "RECORD EXTENDED! Salah extends his all-time Premier League record for Matchweek 1 goals to 11!"
  league_impact → "Trent Alexander-Arnold records his 60th Premier League assist — moving into the top 3 all-time among defenders."
  match_context → "Newcastle have now scored in 14 consecutive home games against Big Six opposition."
  player_stat → "Saka: 23 goals, 14 assists this season — 7 consecutive goal involvements."
  team_stat   → "Arsenal on 74 points — 1 behind Man City with 2 games to play."
  opponent_impact → "Chelsea drop to 5th — losing their Champions League place to Newcastle."

Prioritise in this order:
  (a) milestone — MANDATORY if present
  (b) league_impact
  (c) match_context (what this moment means in the context of this game)
  (d) player_stat
  (e) team_stat
  (f) head_to_head — MANDATORY if present
  (g) opponent_impact

Data rules (CRITICAL):
- DO NOT invent or calculate any numbers — use ONLY exact numbers from Context
- match_context MUST follow: {match_context_format}
- player_stat MUST name the player and include goals + assists where available
- team_stat MUST name the team and include at least two numbers
- league_impact MUST name the team and state exact consequence
- milestone MUST state: player name, current tally, exact target, why it is significant
- head_to_head MUST use exact numbers from commentator_facts.head_to_head

{anti_repetition_rule}
{match_state_summary}

Categories (use exactly one per insight):
league_impact | match_context | player_stat | team_stat | opponent_impact | head_to_head | milestone

Return ONLY JSON. Do NOT include a facts_used field.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLE OUTPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{{
    "lead_story": "GOAL! MOHAMED SALAH EQUALISES FOR LIVERPOOL! Mac Allister slips him through, and Salah buries it into the far corner! RECORD EXTENDED — Salah extends his all-time Premier League record for Matchweek 1 goals to 11!",
    "insights": [
        {{
            "category": "milestone",
            "line": "RECORD EXTENDED! Salah extends his all-time Premier League record for Matchweek 1 goals to 11 — the Egyptian King delivers on opening day yet again!"
        }},
        {{
            "category": "league_impact",
            "line": "Liverpool move into the top 4 — Chelsea drop to 5th and lose their Champions League place."
        }},
        {{
            "category": "match_context",
            "line": "Salah scores for Liverpool against Newcastle — 1-1 at 34'. His 7th goal in his last 6 appearances at St. James' Park."
        }},
        {{
            "category": "player_stat",
            "line": "Salah: 28 goals, 12 assists this season — scored in 6 consecutive away matches."
        }},
        {{
            "category": "head_to_head",
            "line": "Liverpool 9, Newcastle 7 — head-to-head goals in this fixture over the last 5 seasons."
        }}
    ]
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{json.dumps(cleaned, indent=2, default=_json_safe)}

Match History (events in this match before the current event)

{json.dumps(match_history or [], indent=2, default=_json_safe)}
"""

    return prompt
