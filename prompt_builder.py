import json


def build_prompt(event: dict, stats_context: dict) -> str:
    event_type = event.get("event_type", "UNKNOWN")
    player = event.get("player", "Unknown Player")
    team = event.get("team", "Unknown Team")
    minute = event.get("minute", "?")
    score = event.get("score", "Unknown")

    player_stats = stats_context.get("player_stats", {})
    team_stats = stats_context.get("team_stats", {})

    stats_block = ""
    if player_stats:
        stats_block += f"\nPlayer Statistics:\n{json.dumps(player_stats, indent=2)}"
    if team_stats:
        stats_block += f"\nTeam Statistics:\n{json.dumps(team_stats, indent=2)}"

    if not stats_block:
        stats_block = "\nNo historical statistics available for this event."

    prompt = f"""You are an assistant for professional football statisticians working in live broadcast TV.

Current Event:
- Event: {event_type}
- Player: {player}
- Team: {team}
- Minute: {minute}'
- Current Score: {score}
{stats_block}

Instructions:
- Generate exactly five interesting editorial insights suitable for a TV broadcast.
- Only use the statistics supplied above. Never invent or assume any numbers.
- Keep each insight under 20 words.
- Rank them from most interesting to least interesting.
- Return a JSON array of exactly 5 strings, e.g.:
  ["Insight one.", "Insight two.", "Insight three.", "Insight four.", "Insight five."]
- No additional text outside the JSON array."""

    return prompt
