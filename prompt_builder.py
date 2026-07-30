import json


def _flatten_stats(stats_context: dict) -> dict[str, str]:
    """Returns a flat dict of every stat label → exact value for grounding checks."""
    flat = {}
    for section in stats_context.values():
        for entity, values in section.items():
            for k, v in values.items():
                label = f"{entity} {k.replace('_', ' ')}"
                flat[label] = v
    return flat


def build_prompt(event: dict, stats_context: dict) -> str:
    event_type = event.get("event_type", "UNKNOWN")
    player = event.get("player", "Unknown Player")
    team = event.get("team", "Unknown Team")
    minute = event.get("minute", "?")
    score = event.get("score", "Unknown")

    flat = _flatten_stats(stats_context)

    if flat:
        facts_lines = "\n".join(f"  - {label}: {value}" for label, value in flat.items())
        stats_block = f"\nAVAILABLE FACTS (these are the ONLY facts you may reference):\n{facts_lines}"
    else:
        stats_block = "\nNo historical statistics available for this event."

    prompt = f"""You are a data grounding assistant for professional football statisticians working in live broadcast TV.

Current Event:
- Event: {event_type}
- Player: {player}
- Team: {team}
- Minute: {minute}'
- Current Score: {score}
{stats_block}

STRICT RULES — these are non-negotiable for live broadcast accuracy:
1. You MAY ONLY use facts listed above under AVAILABLE FACTS.
2. Every number you write must come directly from AVAILABLE FACTS. Do not round, estimate, or infer.
3. Do NOT reference any player, team, or statistic not listed above.
4. Do NOT use phrases like "reportedly", "estimated", "approximately", or "could be".
5. If there are not enough facts to produce 5 accurate insights, produce fewer rather than invent.
6. Keep each insight under 20 words.
7. Rank them from most interesting to least interesting.
8. Return ONLY a JSON array of strings, no other text:
   ["Insight one.", "Insight two.", ...]"""

    return prompt, flat
