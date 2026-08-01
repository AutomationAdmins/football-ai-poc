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
    Prompt for generating editorial insights
    after an event has been selected.
    """

    cleaned = _clean_context(editorial_context)

    prompt = f"""
You are an editorial football statistician.

Generate editorial insights for this event.

build_insight_prompt

Return ONLY JSON.

Example

[
    "Saka has now scored 23 league goals this season.",
    "This is his seventh goal against Chelsea."
]

Context

{json.dumps(cleaned, indent=2)}
"""

    return prompt