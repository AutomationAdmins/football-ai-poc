import base64
import json
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ai_engine import flatten_for_grounding, generate_insights, rank_events
from event_processor import process_event
from sports_data import get_context
from editorial_context import build_editorial_context
from prompt_builder import build_editorial_prompt, build_insight_prompt
from firestore_client import (
    append_match_event,
    get_match_history,
    write_insight,
    get_all_pending_insights,
    get_used_insight_lines,
    start_insights_listener,
    wait_for_snapshot_update,
    get_latest_snapshot,
    clear_mem_insights,
)
from match_state_tracker import (
    build_match_state,
    detect_player_performance,
    filter_duplicate_insights,
    format_match_state_for_prompt,
    build_match_statistics,
)

_FIXTURE_ID = os.environ.get("FIXTURE_ID", "arsenal-vs-chelsea-2025-08-02")

# ---------------------------------------------------------------------------
# Pub/Sub deduplication — prevent re-delivery from inflating match state
# ---------------------------------------------------------------------------
_processed_events: dict[str, set[str]] = {}  # fixture_id -> set of dedup keys

def _event_dedup_key(event: dict, message_id: str | None = None) -> str:
    """Generate a dedup key for Pub/Sub event redelivery protection.

    Prefer Pub/Sub message_id when available so re-simulations with new messages
    are processed, while true redeliveries are ignored.
    """
    if message_id:
        return f"msg:{message_id}"
    # Fallback for local/manual sends that don't include Pub/Sub metadata.
    return f"event:{event.get('event_type', '')}:{event.get('minute', '')}:{event.get('player', '')}"

app = FastAPI(title="Football AI Editorial Assistant")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/health")
def health():
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Pub/Sub push endpoint — Opta events arrive here from the topic
# ---------------------------------------------------------------------------

from fastapi import BackgroundTasks
import random


def _sanitize(text: str) -> str:
    """Strip non-ASCII problematic Unicode that renders as garbled characters in some browsers."""
    return (text
        .replace('\u2014', ' - ')   # em dash
        .replace('\u2013', ' - ')   # en dash
        .replace('\u2019', "'")     # right single quote
        .replace('\u2018', "'")     # left single quote
        .replace('\u201c', '"')     # left double quote
        .replace('\u201d', '"')     # right double quote
        .replace('\u2026', '...')   # ellipsis
    )


# ---------------------------------------------------------------------------
# Broadcaster-quality commentary generator — context-driven, not templated
# ---------------------------------------------------------------------------

def _goal_opener(goal_type: str, xg: float | None, minute: int | None,
                  player: str, team: str, opponent: str,
                  player_goals_today: int, score: str | None,
                  red_cards: list) -> str:
    """Pick an emotionally varied goal shout based on full match context."""
    late = (minute or 0) >= 85
    very_late = (minute or 0) >= 90
    low_xg = xg is not None and xg < 0.20
    high_xg = xg is not None and xg >= 0.70
    ten_men = len(red_cards) > 0
    h, a = (0, 0)
    if score and "-" in score:
        try:
            h, a = map(int, score.split("-"))
        except ValueError:
            pass
    comeback = (goal_type == "equaliser" and (h + a) > 2)
    dramatic_winner = (goal_type == "go_ahead_goal" and late)

    if player_goals_today >= 3:
        return random.choice([
            f"UNBELIEVABLE! THE HAT-TRICK IS COMPLETE!",
            f"OH MY! THAT IS THREE! THE HAT-TRICK FOR {player.upper()}!",
            f"WOW! WOW! WOW! {player.upper()} HAS HIS HAT-TRICK!",
            f"INCREDIBLE! THREE GOALS FOR {player.upper()} TODAY!",
        ])
    if player_goals_today == 2:
        return random.choice([
            f"OH YES! THE BRACE FOR {player.upper()}!",
            f"HE'S DONE IT AGAIN! THAT'S TWO FOR {player.upper()}!",
            f"SUPERB! {player.upper()} WITH HIS SECOND OF THE AFTERNOON!",
        ])
    if ten_men and goal_type == "equaliser":
        return random.choice([
            f"EXTRAORDINARY! THE TEN MEN EQUALISE!",
            f"OH MY GOODNESS! THEY'VE DONE IT WITH TEN MEN!",
            f"WHAT HEART! {team.upper()} LEVEL IT WITH A MAN DOWN!",
        ])
    if very_late and goal_type == "equaliser":
        return random.choice([
            f"AT THE DEATH! CAN YOU BELIEVE IT!",
            f"OH NO! OH NO! THEY'VE EQUALISED IN STOPPAGE TIME!",
            f"LAST GASP! THE COMEBACK IS COMPLETE!",
        ])
    if late and dramatic_winner:
        return random.choice([
            f"YESSS! A LATE, LATE WINNER!",
            f"OH WHAT A MOMENT! THE WINNER IN THE DYING MINUTES!",
            f"DRAMA! DRAMA! DRAMA! {player.upper()} WINS IT LATE!",
        ])
    if comeback:
        return random.choice([
            f"THEY'RE LEVEL! THE COMEBACK IS ON!",
            f"OH WOW! {team.upper()} PULL LEVEL! WHAT A GAME!",
            f"UNREAL! THEY'VE EQUALISED! THE CROWD ARE ON THEIR FEET!",
        ])
    if low_xg:
        return random.choice([
            f"OH WHAT A GOAL! WHERE DID THAT COME FROM!",
            f"SENSATIONAL! ABSOLUTELY SENSATIONAL FROM {player.upper()}!",
            f"WOW! FROM NOWHERE — AND IT'S IN THE NET!",
            f"STUNNING! NOBODY EXPECTED THAT!",
        ])
    if high_xg and goal_type == "go_ahead_goal":
        return random.choice([
            f"AND THEY'VE TAKEN THE LEAD!",
            f"CLINICAL! ABSOLUTELY CLINICAL FINISH!",
            f"YES! {player.upper()} MAKES IT COUNT!",
        ])
    if goal_type == "equaliser":
        return random.choice([
            f"OH YES! {team.upper()} ARE LEVEL!",
            f"BACK IN IT! {player.upper()} DRAGS THEM BACK INTO THIS!",
            f"THE EQUALISER! WHAT A RESPONSE FROM {team.upper()}!",
        ])
    if goal_type == "go_ahead_goal":
        return random.choice([
            f"THE LEAD! {team.upper()} GO IN FRONT!",
            f"OH THAT'S BRILLIANT! {player.upper()} PUTS THEM AHEAD!",
            f"YESSS! {team.upper()} HAVE THE LEAD NOW!",
        ])
    # Default varied goal openers
    return random.choice([
        f"GOAL! OH WHAT A FINISH!",
        f"IN THE NET! {player.upper()} SCORES!",
        f"YES! {player.upper()} PUTS {team.upper()} AHEAD!",
        f"GOAL! LOVELY MOVE AND {player.upper()} CONVERTS!",
        f"OH THAT IS BEAUTIFUL FROM {player.upper()}!",
    ])


def _chance_desc(xg: float | None, x: float | None, pressure: int | None) -> str:
    """Describe how the goal was scored using xG, shot location and pressure."""
    if xg is None:
        return ""
    if xg >= 0.75:
        phrases = ["a clinical finish from close range", "a composed finish — couldn't miss from there",
                   "virtually an open goal and he doesn't waste it", "a tap-in — the keeper had no chance"]
    elif xg >= 0.40:
        phrases = ["a well-taken finish from inside the box", "a powerful strike from a good position",
                   "a composed slot into the corner", "good movement to create the angle and finish it"]
    elif xg >= 0.20:
        phrases = ["a fine finish against the odds", "a low-probability chance — but he took it brilliantly",
                   "a speculative effort that found the corner"]
    else:
        phrases = ["an absolute rocket — nobody saw that coming!",
                   "a stunning strike from distance — the keeper was rooted to the spot!",
                   "from virtually nothing — a moment of individual brilliance!"]
    desc = random.choice(phrases)
    if pressure and pressure >= 80 and xg and xg < 0.4:
        desc += " — under enormous pressure!"
    return desc


def _buildup_desc(build_up_players: list | None, player: str | None) -> str:
    """Describe the build-up play — always starts with a capital letter."""
    if not build_up_players:
        return ""
    if len(build_up_players) == 1:
        return random.choice([
            f"{build_up_players[0]} picks out {player} with a perfectly weighted pass",
            f"{build_up_players[0]} with a sublime ball through to {player}",
            f"Great work from {build_up_players[0]} to tee up {player}",
        ])
    elif len(build_up_players) == 2:
        templates = [
            f"{build_up_players[0]} and {build_up_players[1]} combine beautifully",
            f"Lovely link play between {build_up_players[0]} and {build_up_players[1]}",
            f"{build_up_players[0]} lays it off to {build_up_players[1]}, who finds {player}",
            f"What a move! {build_up_players[0]} and {build_up_players[1]} tear them apart",
            f"{build_up_players[0]} and {build_up_players[1]} — outstanding combination play",
        ]
        return random.choice(templates)
    return f"A flowing move involving {', '.join(build_up_players[:-1])} and {build_up_players[-1]}"


def _match_narrative(goals_by_player: dict, red_cards: list, score: str | None,
                      team: str, opponent: str, minute: int | None) -> str:
    """Generate a sentence about the current match situation."""
    h, a = (0, 0)
    if score and "-" in score:
        try:
            h, a = map(int, score.split("-"))
        except ValueError:
            pass
    total_goals = h + a
    min_val = minute or 0
    narratives = []
    if total_goals >= 4:
        narratives.append(f"What a game this has been — {total_goals} goals already in this clash!")
    if red_cards:
        rc = red_cards[-1]
        mins_short = min_val - rc.get("minute", min_val)
        if mins_short > 0:
            narratives.append(f"{rc.get('team')} have been playing with ten men for {mins_short} minutes now.")
    if h == a and total_goals > 0 and min_val >= 80:
        narratives.append(f"Neither side able to find a winner — drama still possible with {90 - min_val} minutes left.")
    if narratives:
        return random.choice(narratives)
    return ""


def _broadcaster_lead(event_type: str, player: str | None, team: str | None,
                       opponent: str | None, score: str | None, minute: int | None,
                       match_state: dict, editorial_ctx: dict,
                       processed: dict | None = None) -> str:
    """Generate a Sky Sports live commentary lead — fully context-driven."""
    processed = processed or {}
    goals_by_player = (match_state or {}).get("goals_by_player", {})
    red_cards = (match_state or {}).get("red_cards", [])
    player_goals_today = goals_by_player.get(player, 0) if player else 0
    score_str = score or ""
    min_str = f"{minute}'" if minute else ""
    facts = ((editorial_ctx or {}).get("commentator_facts") or {})
    player_ctx = ((editorial_ctx or {}).get("player") or {})
    goal_type = facts.get("goal_type", "")

    # xG, build-up, pressure from raw event
    xg = processed.get("xG")
    build_up = processed.get("build_up_players") or []
    pressure = processed.get("pressure_index")
    x = processed.get("x")

    # Stakes consequence
    stakes_keys = ("promotion_stakes", "stakes_line", "promotion_consequence",
                   "champions_league_stakes", "title_race")
    consequence = next((facts.get(k) for k in stakes_keys if facts.get(k)), "")

    # Season milestone note
    notes = player_ctx.get("notes") or player_ctx.get("next_milestone") or ""

    if event_type == "GOAL":
        chance = _chance_desc(xg, x, pressure)
        buildup = _buildup_desc(build_up, player)
        opener = _goal_opener(goal_type, xg, minute, player or "", team or "",
                              opponent or "", player_goals_today, score_str, red_cards)

        if player_goals_today >= 3:
            if buildup and chance:
                lead = f"{opener} {buildup}, and {player.upper()} makes it three! {chance[0].upper() + chance[1:]}. {score_str} at {min_str}!"
            elif buildup:
                lead = f"{opener} {buildup}, and {player.upper()} completes the hat-trick! {score_str} at {min_str}!"
            else:
                lead = f"{opener} {player.upper()} — {score_str} at {min_str} for {team}! Three goals in one game!"
        elif player_goals_today == 2:
            if buildup and chance:
                lead = f"{opener} {buildup} — {chance}. {score_str} at {min_str}."
            elif buildup:
                lead = f"{opener} {buildup}, and {player.upper()} makes it two for {team}! {score_str} at {min_str}."
            else:
                lead = f"{opener} {score_str} at {min_str}. What an impact from {player}!"
        elif buildup and chance:
            lead = f"{opener} {buildup} — {chance}. {score_str} at {min_str}."
        elif buildup:
            lead = f"{opener} {buildup}, and {player.upper()} finishes it off for {team}! {score_str} at {min_str}."
        elif chance:
            lead = f"{opener} {player.upper()} for {team} — {chance}. {score_str} at {min_str}."
        else:
            lead = f"{opener} {player.upper()} for {team} — {score_str} at {min_str} against {opponent}!"

        if notes and any(c.isdigit() for c in str(notes)):
            lead += f" {notes}"
        elif consequence:
            lead += f" {consequence}."
        return lead

    elif event_type == "RED_CARD":
        mins_left = 90 - (minute or 0)
        if pressure and pressure >= 80:
            reason = random.choice([
                "a desperate, reckless challenge",
                "a horrific lunge — he had to go",
                "a last-man foul — no choice for the referee",
            ])
            opener = random.choice([
                f"OH NO! RED CARD!",
                f"OFF HE GOES! RED CARD!",
                f"HE'S GONE! THE REFEREE HAS NO CHOICE!",
            ])
            lead = f"{opener} {player.upper()} — {reason}! {team} are down to ten men at {min_str}. {score_str}."
        else:
            opener = random.choice([
                f"RED CARD! OH DEAR!",
                f"OFF! {player.upper()} IS OFF!",
                f"THE RED CARD COMES OUT!",
            ])
            lead = f"{opener} {player.upper()} is sent off — {team} with ten men against {opponent} at {min_str}. {score_str}."
        if mins_left > 0:
            drama = random.choice([
                f" {mins_left} long minutes to hold on.",
                f" Can {team} hang on with ten men?",
                f" What a mountain to climb for {team} now.",
            ])
            lead += drama
        return lead

    elif event_type == "PENALTY":
        buildup = _buildup_desc(build_up, player) if build_up else ""
        opener = random.choice([
            f"PENALTY CONVERTED!",
            f"HE SENDS THE KEEPER THE WRONG WAY!",
            f"COOL AS YOU LIKE FROM THE SPOT!",
        ])
        if buildup:
            lead = f"{opener} {buildup} — and {player.upper()} steps up and tucks it away for {team}! {score_str} at {min_str}!"
        else:
            lead = f"{opener} {player.upper()} for {team.upper()}! {score_str} at {min_str} against {opponent}!"
        if consequence:
            lead += f" {consequence}."
        return lead

    elif event_type == "OWN_GOAL":
        return random.choice([
            f"OH NO! OWN GOAL! {player.upper()} turns it into his own net — {team} are gifted the goal! {score_str} at {min_str}!",
            f"OH DEAR! WHAT MISFORTUNE! The ball goes in off {player.upper()}! {score_str} at {min_str} — a cruel moment.",
            f"OOH! {player.upper()} won't want to see that again — into his own net! {score_str} at {min_str}. Dreadful luck.",
        ])

    elif event_type == "VAR_DECISION":
        return random.choice([
            f"HOLD ON — VAR IS CHECKING THIS! The stadium falls silent at {min_str} in {team} vs {opponent}, {score_str}. The referee is heading to the monitor...",
            f"OH! IT'S GOING TO VAR! Controversy at {min_str} — {score_str}. The officials are reviewing the incident now.",
            f"WAIT — IS THIS BEING CHECKED? VAR intervenes at {min_str}. {team} vs {opponent}, {score_str}. Nerves all round.",
        ])

    elif event_type == "HALF_TIME":
        h, a = (score_str.split("-") if score_str and "-" in score_str else ("0", "0"))
        h_i, a_i = int(h), int(a)
        goals_list = [(p, g) for p, g in goals_by_player.items() if g >= 1]
        scorers_str = ""
        if goals_list:
            scorers_str = " — goals from " + " and ".join(f"{p} ({g})" if g > 1 else p for p, g in goals_list[:3])
        if h_i == a_i == 0:
            opts = [
                f"A tight, cagey first half — nothing to separate {team} and {opponent}. Goalless at the break.",
                f"A battle in midfield — both sides cancelling each other out. No goals yet, but plenty to talk about.",
            ]
        elif h_i == a_i:
            opts = [
                f"What a first half! End to end stuff — {score_str} at the break{scorers_str}. Plenty more to come.",
                f"Both sides have had moments — {score_str} at the interval. Neither can afford another mistake.",
            ]
        elif h_i > a_i:
            opts = [
                f"{team} will be pleased with that — {score_str} up{scorers_str}. {opponent} need to respond.",
                f"The home side in the driving seat at half-time — {score_str}{scorers_str}. Can {opponent} find a way back?",
            ]
        else:
            opts = [
                f"{opponent} head in front at the break — {score_str}{scorers_str}. {team} will need to regroup.",
                f"It's been {opponent}'s half — they lead {score_str} at the interval{scorers_str}. Tough watch for {team}.",
            ]
        return f"HALF-TIME! {random.choice(opts)}"

    elif event_type == "FULL_TIME":
        h, a = (score_str.split("-") if score_str and "-" in score_str else ("0", "0"))
        h_i, a_i = int(h), int(a)
        goals_list = [(p, g) for p, g in goals_by_player.items() if g >= 1]
        hat_trick_player = next((p for p, g in goals_list if g >= 3), None)
        brace_player = next((p for p, g in goals_list if g == 2), None)
        margin = abs(h_i - a_i)
        winner = team if h_i > a_i else (opponent if a_i > h_i else None)
        loser = opponent if h_i > a_i else (team if a_i > h_i else None)
        hero = f"{hat_trick_player} the hat-trick hero" if hat_trick_player else (f"{brace_player} with a brace" if brace_player else "")

        if winner is None:
            opts = [
                f"FULL-TIME! A point apiece — {score_str}. {team} and {opponent} share the spoils in a breathless contest!",
                f"FULL-TIME! It ends {score_str}! Honours even — but what a game it was!",
            ]
        elif margin >= 3:
            opts = [
                f"FULL-TIME! {winner.upper()} WIN CONVINCINGLY — {score_str}! A dominant display from start to finish.",
                f"FULL-TIME! {loser.upper()} well beaten — {winner.upper()} run out {score_str} winners today!",
            ]
        elif red_cards and winner:
            opts = [f"FULL-TIME! TEN-MAN {team.upper()} {'HOLD ON FOR AN INCREDIBLE WIN' if winner == team else 'FALL SHORT'} — {score_str}! What resilience!"]
        else:
            if (minute or 0) >= 88:
                opts = [
                    f"FULL-TIME! WHAT A FINISH! {winner.upper()} WIN IT {score_str} — DRAMA IN THE DYING MINUTES!",
                    f"FULL-TIME! {winner.upper()} SNATCH IT AT THE DEATH — {score_str}! THE GROUND ERUPTS!",
                ]
            else:
                opts = [
                    f"FULL-TIME! {winner.upper()} WIN {score_str} against {opponent.upper()}. A well-deserved victory.",
                    f"FULL-TIME! Three points for {winner.upper()} — {score_str}. {loser.upper()} will be disappointed.",
                ]
        result = random.choice(opts)
        if hero:
            result += f" {hero}."
        if consequence:
            result += f" {consequence}."
        return result

    return f"{event_type.replace('_', ' ')} — {team} {score_str} {opponent} at {min_str}."


def _broadcaster_insights(event_type: str, player: str | None, team: str | None,
                           opponent: str | None, score: str | None, minute: int | None,
                           match_state: dict, editorial_ctx: dict,
                           stats_context: dict, processed: dict | None = None) -> list[dict]:
    """Build Sky Sports stat overlay cards — grounded in actual data."""
    processed = processed or {}
    insights = []
    facts = ((editorial_ctx or {}).get("commentator_facts") or {})
    player_ctx = ((editorial_ctx or {}).get("player") or {})
    team_ctx = ((editorial_ctx or {}).get("team") or {})
    goals_by_player = (match_state or {}).get("goals_by_player", {})
    red_cards = (match_state or {}).get("red_cards", [])
    score_prog = (match_state or {}).get("score_progression", [])
    player_goals_today = goals_by_player.get(player, 0) if player else 0
    xg = processed.get("xG")
    build_up = processed.get("build_up_players") or []
    pressure = processed.get("pressure_index")
    pass_acc = processed.get("pass_accuracy")
    min_str = f"{minute}'" if minute else ""

    # --- MILESTONE: hat-trick, brace, career milestone ---
    if player and player_goals_today >= 3:
        season_goals = player_ctx.get("season_goals")
        if season_goals:
            insights.append({"category": "milestone",
                "line": f"OH WHAT A HAT-TRICK! {player.upper()} HAS THREE TODAY — {season_goals} for the season now! Absolutely unstoppable!"})
        else:
            insights.append({"category": "milestone",
                "line": f"THE HAT-TRICK IS COMPLETE! {player} has been sensational — three goals in one match, what a performance!"})
    elif player and player_goals_today == 2:
        season_goals = player_ctx.get("season_goals")
        if season_goals:
            insights.append({"category": "milestone",
                "line": f"THE BRACE! {player.upper()} WITH TWO TODAY — that's {season_goals} for the season! He cannot stop scoring!"})
        else:
            insights.append({"category": "milestone",
                "line": f"TWO GOALS! {player} is having the game of his life — {team} are absolutely in control now!"})
    else:
        career_goals = player_ctx.get("career_goals_at_club")
        goals_to_milestone = player_ctx.get("goals_to_next_milestone")
        next_milestone_label = player_ctx.get("next_milestone")
        if career_goals and goals_to_milestone is not None and next_milestone_label:
            target = career_goals + goals_to_milestone
            insights.append({"category": "milestone",
                "line": f"THE MILESTONES ARE COMING! {career_goals} career goals for {team} — just {goals_to_milestone} away from {target}! History beckons for {player}!"})

    # --- LEAGUE IMPACT ---
    stakes_keys = ("stakes_line", "promotion_stakes", "promotion_consequence",
                   "champions_league_stakes", "title_race")
    stakes = next((facts.get(k) for k in stakes_keys if facts.get(k)), "")
    if stakes:
        insights.append({"category": "league_impact", "line": f"THE STAKES COULDN'T BE HIGHER! {stakes}"})

    # --- HOW IT WAS SCORED: xG + build-up combined ---
    if event_type in ("GOAL", "PENALTY"):
        ctx_parts = []
        if xg is not None:
            if xg >= 0.75:
                ctx_parts.append(f"xG {xg:.2f} — he had to score from there and he did! Absolutely clinical from {player}!")
            elif xg >= 0.40:
                ctx_parts.append(f"xG {xg:.2f} — a great opportunity and {player} took it brilliantly! No hesitation whatsoever!")
            elif xg >= 0.20:
                ctx_parts.append(f"xG {xg:.2f} — not the easiest chance but {player} made it count! Great composure!")
            elif xg >= 0.10:
                ctx_parts.append(f"xG just {xg:.2f} — barely a chance on paper! {player} has conjured something out of nothing!")
            else:
                ctx_parts.append(f"xG only {xg:.2f} — that should NOT have gone in! What a sensational strike from {player}!")
        if build_up:
            if len(build_up) >= 2:
                ctx_parts.append(f"What a move that was — {build_up[0]} and {build_up[1]} tore the defence apart to set up {player}!")
            elif len(build_up) == 1:
                ctx_parts.append(f"{build_up[0]} with the perfect assist — {player} was never going to miss that!")
        if ctx_parts:
            insights.append({"category": "match_context", "line": " ".join(ctx_parts)})

    # --- RED CARD CONTEXT ---
    if event_type == "RED_CARD" and red_cards:
        rc = red_cards[-1]
        mins_short = (minute or 0) - rc.get("minute", minute or 0)
        if mins_short > 0:
            insights.append({"category": "match_context",
                "line": f"DOWN TO TEN MEN! {rc.get('team')} have been a man short for {mins_short} minutes — can they hold on? {90 - (minute or 0)} minutes left at {score}!"})
        elif pressure and pressure >= 80:
            insights.append({"category": "match_context",
                "line": f"WHAT WAS HE THINKING?! Pressure index at {pressure} — that was desperate, reckless defending from {player}!"})

    # --- VS OPPONENT CAREER RECORD ---
    if player and opponent and event_type in ("GOAL", "PENALTY", "RED_CARD"):
        opp_slug = opponent.lower().replace(" ", "_")
        career_vs_opp = player_ctx.get(f"goals_vs_{opp_slug}_career")
        apps_vs_opp = player_ctx.get(f"appearances_vs_{opp_slug}")
        if career_vs_opp:
            if apps_vs_opp:
                insights.append({"category": "player_stat",
                    "line": f"HE LOVES THIS FIXTURE! {career_vs_opp} career goals in {apps_vs_opp} appearances against {opponent} — {player} is absolutely lethal against this opposition!"})
            else:
                insights.append({"category": "player_stat",
                    "line": f"WHAT A RECORD! {career_vs_opp} career goals for {player} against {opponent} — they just cannot stop him!"})

    # --- PLAYER SEASON STATS (from historical CSV only) ---
    if player and player_ctx and event_type in ("GOAL", "PENALTY"):
        season_goals = player_ctx.get("season_goals")
        season_assists = player_ctx.get("season_assists")
        streak_data = player_ctx.get("scoring_streak") or {}
        streak = (player_ctx.get("consecutive_scoring_matches") or
                  player_ctx.get("consecutive_goal_involvements"))
        streak_goals = streak_data.get("goals_in_longest_streak") if isinstance(streak_data, dict) else None
        parts = []
        if season_goals is not None:
            goal_word = "goal" if season_goals == 1 else "goals"
            parts.append(f"{season_goals} {goal_word} this season")
        if season_assists is not None:
            parts.append(f"{season_assists} assists")
        if streak:
            streak_str = f"scoring in {streak} consecutive matches"
            if streak_goals:
                streak_str += f" — {streak_goals} goals in that incredible run"
            parts.append(streak_str)
        if parts:
            opener = random.choice([
                f"WHAT A SEASON {player.upper()} IS HAVING!",
                f"THE NUMBERS DON'T LIE!",
                f"JUST LOOK AT THOSE STATS!",
                f"REMARKABLE FORM FROM {player.upper()}!",
            ])
            insights.append({"category": "player_stat",
                "line": f"{opener} {', '.join(parts)}."})

    # --- PASSING / CONTROL ---
    if pass_acc and event_type in ("GOAL", "HALF_TIME", "FULL_TIME"):
        if pass_acc >= 85:
            insights.append({"category": "team_stat",
                "line": f"TOTAL DOMINATION! {team} passing at {pass_acc}% accuracy — they are completely controlling this game!"})
        elif pass_acc <= 72:
            insights.append({"category": "team_stat",
                "line": f"STRUGGLING IN POSSESSION! Only {pass_acc}% pass accuracy for {team} — they are under enormous pressure right now!"})

    # --- TEAM STATS ---
    if team_ctx:
        points = team_ctx.get("points")
        position = team_ctx.get("position") or team_ctx.get("league_position")
        gd = team_ctx.get("goal_difference")
        if points and position:
            pos_int = int(position) if str(position).isdigit() else None
            if pos_int:
                suffix = "th" if 11 <= pos_int <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(pos_int % 10, "th")
                pos_str = f"{pos_int}{suffix}"
            else:
                pos_str = str(position)
            gd_str = f", GD {gd:+d}" if isinstance(gd, int) else ""
            table_opener = random.choice([
                f"THIS IS WHAT IT MEANS!",
                f"THE TABLE TELLS THE STORY!",
                f"LOOK WHERE THIS PUTS THEM!",
            ])
            insights.append({"category": "team_stat",
                "line": f"{table_opener} {team}: {points} pts, {pos_str} in the table{gd_str}!"})

    # --- HEAD TO HEAD ---
    h2h = facts.get("head_to_head") or ""
    if h2h:
        h2h_line = h2h if h2h.lower().startswith("head-to-head") else f"Head-to-head: {h2h}"
        insights.append({"category": "head_to_head",
            "line": f"THE HISTORY BOOKS! {h2h_line} — and this result adds another chapter!"})

    # --- OPPONENT IMPACT ---
    opp_impact = facts.get("opponent_consequence") or facts.get("opponent_stakes") or ""
    if opp_impact:
        insights.append({"category": "opponent_impact",
            "line": f"AND WHAT DOES THIS MEAN FOR {opponent.upper() if opponent else 'THE OPPOSITION'}?! {opp_impact}"})

    # --- EVENT-TYPE CATEGORY FILTER ---
    # Only return categories relevant to this event type
    allowed = {
        "GOAL": {"milestone", "match_context", "player_stat"},
        "PENALTY": {"milestone", "match_context", "player_stat"},
        "RED_CARD": {"match_context", "milestone"},
        "HALF_TIME": {"match_context", "tactical", "head_to_head", "milestone"},
        "FULL_TIME": {"match_context", "tactical", "milestone", "league_impact", "player_stat"},
    }
    cats = allowed.get(event_type, set())
    if cats:
        insights = [i for i in insights if i.get("category") in cats]

    return [i for i in insights if i.get("line")][:5]


def _build_player_stat_line(editorial_ctx: dict, processed: dict) -> str | None:
    player_name = processed.get("player")
    if not player_name:
        return None

    perf = editorial_ctx.get("player_performance") or {}
    facts = editorial_ctx.get("commentator_facts") or {}
    player_ctx = editorial_ctx.get("player") or {}

    goals_today = perf.get("goals_today", 0)
    season_goals = player_ctx.get("season_goals")
    season_assists = player_ctx.get("season_assists")

    parts: list[str] = []

    if goals_today >= 3:
        parts.append(f"{player_name} has a hat-trick ({goals_today} goals today)")
    elif goals_today == 2:
        parts.append(f"{player_name} has a brace ({goals_today} goals today)")
    elif goals_today == 1:
        parts.append(f"{player_name} has scored {goals_today} goal today")

    if season_goals is not None and season_assists is not None:
        parts.append(f"{season_goals} goals and {season_assists} assists this season")
    elif season_goals is not None:
        parts.append(f"{season_goals} goals this season")

    # Add one concise quality cue if available
    highlight = facts.get("player_highlight")
    if isinstance(highlight, str):
        for segment in [s.strip() for s in highlight.split(";")]:
            if "xG" in segment or "Build-up:" in segment:
                parts.append(segment)
                break

    if not parts:
        return None

    return " — ".join(parts)


def _ensure_player_stat_insight(insights: list[dict], editorial_ctx: dict, processed: dict) -> list[dict]:
    has_player_stat = any(i.get("category") == "player_stat" for i in insights)
    if has_player_stat:
        return insights

    line = _build_player_stat_line(editorial_ctx, processed)
    if not line:
        return insights

    return insights + [{"category": "player_stat", "line": line, "facts_used": []}]


def _compute_editorial_weight(event: dict, editorial_ctx: dict, match_state: dict = None) -> int:
    """
    Compute editorial importance weight for an event.
    Higher = more important to show as lead story.
    
    Weighting philosophy (from production requirements):
    - A Man Utd goal is generally more important than a Salford goal
    - BUT if Salford equalise to go top of the league, that's more relevant
    - Context is everything: promotion, relegation, title race, hat-tricks
    """
    weight = 0
    event_type = (event.get("event_type") or "").upper()
    lead = (editorial_ctx.get("commentator_facts", {}) if isinstance(editorial_ctx, dict) else {})
    league = event.get("league") or editorial_ctx.get("event", {}).get("league") or ""
    
    # --- LEAGUE TIER BASE WEIGHT ---
    # Premier League gets a base boost, but context can override
    league_lower = league.lower() if league else ""
    if "premier league" in league_lower:
        weight += 20
    elif "championship" in league_lower:
        weight += 10
    elif "league one" in league_lower or "league two" in league_lower:
        weight += 5
    
    # --- STAKES MULTIPLIER (this is the big one) ---
    # Promotion/relegation/title-deciding moments override league tier
    stakes_text = ""
    if isinstance(lead, dict):
        for key in ("promotion_stakes", "stakes_line", "promotion_consequence", 
                    "champions_league_stakes", "title_race"):
            val = lead.get(key, "")
            if val:
                stakes_text += " " + str(val)
    
    stakes_lower = stakes_text.lower()
    if "promoted" in stakes_lower or "promotion" in stakes_lower:
        weight += 80
    if "relegated" in stakes_lower or "relegation" in stakes_lower:
        weight += 70
    if "title" in stakes_lower or "champions league" in stakes_lower:
        weight += 60
    if "top of the league" in stakes_lower or "go top" in stakes_lower:
        weight += 50
    
    # --- EVENT TYPE ---
    if event_type == "FULL_TIME":
        weight += 50  # Final result is always the definitive lead story
    elif event_type == "HALF_TIME":
        weight += 10
    elif event_type == "RED_CARD":
        weight += 40
    elif event_type == "GOAL":
        weight += 30
    elif event_type == "PENALTY":
        weight += 35
    
    # --- GOAL CONTEXT ---
    score = event.get("score", "")
    if score and event_type == "GOAL":
        parts = score.split("-")
        if len(parts) == 2:
            try:
                h, a = int(parts[0]), int(parts[1])
                if h == a:
                    weight += 25  # Equaliser
                elif h + a == 1:
                    weight += 15  # Opening goal
                elif abs(h - a) == 1 and (h + a) > 2:
                    weight += 20  # Going ahead in a tight game
            except ValueError:
                pass
    
    # --- PLAYER PERFORMANCE ---
    if match_state:
        player = event.get("player", "")
        if player:
            player_goals = match_state.get("goals_by_player", {}).get(player, 0)
            if player_goals >= 3:
                weight += 100  # Hat-trick is always the biggest story
            elif player_goals == 2:
                weight += 40  # Brace
        else:
            # For FULL_TIME/HALF_TIME, check if any player has a hat-trick
            goals_by_player = match_state.get("goals_by_player", {})
            max_goals = max(goals_by_player.values()) if goals_by_player else 0
            if max_goals >= 3:
                weight += 100
            elif max_goals == 2:
                weight += 40
    
    # --- MINUTE (late drama is more dramatic) ---
    minute = event.get("minute") or 0
    if minute >= 85:
        weight += 20  # Late drama
    elif minute >= 75:
        weight += 10
    
    return weight


def _build_match_summary_insights(match_stats: dict, event_type: str, editorial_ctx: dict = None) -> list[dict]:
    """
    Build broadcaster-friendly match summary insights for HALF_TIME and FULL_TIME.
    Written in natural language so commentators can read them out directly.
    """
    insights = []
    
    home_team = match_stats.get("home_team", "Home")
    away_team = match_stats.get("away_team", "Away")
    score = match_stats.get("score", "0-0")
    minute = match_stats.get("minute", 0)
    period = "Half-time" if event_type == "HALF_TIME" else "Full-time"
    
    # Build the lead story as a readable narrative
    home_goals = match_stats.get("goals_by_team", {}).get(home_team, 0)
    away_goals = match_stats.get("goals_by_team", {}).get(away_team, 0)
    goals_by_player = match_stats.get("goals_by_player", {})
    total_goals = match_stats.get("total_goals", 0)
    is_full_time = event_type == "FULL_TIME"
    
    # --- LEAD STORY: Narrative headline ---
    lead_parts = []
    
    # Who's winning and how?
    if home_goals > away_goals:
        margin = home_goals - away_goals
        if is_full_time:
            if margin >= 3:
                lead_parts.append(f"{home_team} thrash {away_team} {score}")
            elif margin == 2:
                lead_parts.append(f"{home_team} beat {away_team} {score}")
            else:
                lead_parts.append(f"{home_team} win {score} against {away_team}")
        else:
            if margin >= 3:
                lead_parts.append(f"{home_team} are dominant, leading {score} against {away_team}")
            elif margin == 2:
                lead_parts.append(f"{home_team} in control, leading {score} against {away_team}")
            else:
                lead_parts.append(f"{home_team} lead {score} against {away_team}")
    elif away_goals > home_goals:
        margin = away_goals - home_goals
        if is_full_time:
            if margin >= 3:
                lead_parts.append(f"{away_team} thrash {home_team} {score}")
            elif margin == 2:
                lead_parts.append(f"{away_team} beat {home_team} {score}")
            else:
                lead_parts.append(f"{away_team} win {score} at {home_team}")
        else:
            if margin >= 3:
                lead_parts.append(f"{away_team} are dominant, leading {score} against {home_team}")
            elif margin == 2:
                lead_parts.append(f"{away_team} in control, {score} at {home_team}")
            else:
                lead_parts.append(f"{away_team} lead {score} at {home_team}")
    else:
        if total_goals == 0:
            lead_parts.append(f"Nothing to separate {home_team} and {away_team}, goalless at {period.lower()}")
        else:
            if is_full_time:
                lead_parts.append(f"{home_team} and {away_team} share the points in a {score} draw")
            else:
                lead_parts.append(f"All square at {score} between {home_team} and {away_team}")
    
    # Add star performer to lead
    top_scorer = max(goals_by_player.items(), key=lambda x: x[1]) if goals_by_player else None
    if top_scorer and top_scorer[1] >= 2:
        player, count = top_scorer
        if count >= 3:
            lead_parts.append(f"{player} the hero with a stunning hat-trick")
        else:
            lead_parts.append(f"{player} with a brace")
    
    # Red card drama in lead
    if match_stats.get("red_cards"):
        red = match_stats["red_cards"][0]
        lead_parts.append(f"{red['team']} down to ten men after {red['player']}'s red card")
    
    # League stakes — the MOST IMPORTANT context for full-time
    if is_full_time and editorial_ctx:
        facts = editorial_ctx.get("commentator_facts", {})
        # Check for promotion/relegation/title consequence
        promotion_consequence = facts.get("promotion_consequence") or ""
        stakes = facts.get("stakes_line") or ""
        promotion_stakes = facts.get("promotion_stakes") or ""
        
        # Determine what happened based on result
        winner = None
        if home_goals > away_goals:
            winner = home_team
        elif away_goals > home_goals:
            winner = away_team
        
        # Build the consequence line
        consequence = ""
        if promotion_consequence and winner:
            # Convert conditional "If X win today they will..." to definitive "X will..."
            con = promotion_consequence
            # Remove conditional prefixes
            for prefix in (
                f"If {home_team} win today ",
                f"If {away_team} win today ",
                f"If {winner} win today ",
                "If they win today ",
                "If Leeds win today ",
            ):
                if con.startswith(prefix):
                    con = con[len(prefix):]
                    break
            # Remove leading "they " since we'll add the team name
            if con.startswith("they "):
                con = con[5:]
            elif con.startswith("They "):
                con = con[5:]
            # Make definitive with team name
            consequence = f"{winner} {con}" if con else ""
        elif promotion_stakes:
            # Also convert conditional stakes to definitive
            ps = promotion_stakes
            if winner and "win or draw" in ps.lower():
                # e.g. "A win or draw confirms..." → confirmed
                ps = ps.replace("A win or draw confirms", f"{winner} have confirmed").replace("a win or draw confirms", f"{winner} have confirmed")
            consequence = ps
        elif stakes and ("promot" in stakes.lower() or "relegat" in stakes.lower() or "title" in stakes.lower()):
            consequence = stakes
        
        if consequence:
            lead_parts.append(consequence)
    
    lead_story = " — ".join(lead_parts)
    
    insights.append({
        "category": "match_context",
        "line": lead_story,
        "facts_used": ["score", "teams", "goals_by_player"]
    })
    
    # --- GOAL STORY: Who scored and how ---
    if match_stats.get("scorers"):
        scorers_by_team = {}
        for scorer in match_stats["scorers"]:
            team = scorer["team"]
            if team not in scorers_by_team:
                scorers_by_team[team] = []
            
            # Translate xG into plain English
            xg = scorer.get("xG", 0)
            if xg >= 0.7:
                chance_desc = "from a clear-cut chance"
            elif xg >= 0.3:
                chance_desc = "from a good position"
            elif xg >= 0.1:
                chance_desc = "against the odds"
            else:
                chance_desc = "from virtually nothing"
            
            scorers_by_team[team].append({
                "player": scorer["player"],
                "minute": scorer["minute"],
                "chance_desc": chance_desc,
            })
        
        for team in [home_team, away_team]:
            if team in scorers_by_team and scorers_by_team[team]:
                scorer_strs = []
                for s in scorers_by_team[team]:
                    scorer_strs.append(f"{s['player']} ({s['minute']}', {s['chance_desc']})")
                
                goal_count = len(scorer_strs)
                if goal_count == 1:
                    line = f"THE GOAL THAT MATTERED! {team}: {scorer_strs[0]}"
                else:
                    line = f"WHAT A PERFORMANCE FROM {team.upper()}! {goal_count} goals — {', '.join(scorer_strs)}"
                
                insights.append({
                    "category": "player_stat",
                    "line": line,
                    "facts_used": ["scorers"]
                })
    
    # --- MILESTONES: Hat-tricks, braces ---
    if goals_by_player:
        for player, count in sorted(goals_by_player.items(), key=lambda x: x[1], reverse=True):
            if count >= 3:
                insights.append({
                    "category": "milestone",
                    "line": f"OH WHAT A PERFORMANCE! {player.upper()} TAKES THE MATCH BALL — {count} goals and an absolutely sensational hat-trick! What a player!",
                    "facts_used": ["goals_by_player"]
                })
            elif count == 2:
                insights.append({
                    "category": "milestone",
                    "line": f"THE BRACE! {player} with two goals — a real match-winner and a devastating impact on this game!",
                    "facts_used": ["goals_by_player"]
                })
    
    # --- TACTICAL STORY: Finishing quality ---
    home_xg = match_stats.get("xG_by_team", {}).get(home_team, 0.0)
    away_xg = match_stats.get("xG_by_team", {}).get(away_team, 0.0)
    
    if home_xg > 0 or away_xg > 0:
        # Tell the story of who's been clinical vs wasteful
        lines = []
        
        if home_goals > 0 and home_xg > 0:
            home_ratio = home_goals / home_xg
            if home_ratio > 2:
                lines.append(f"{home_team} have been ruthlessly clinical, scoring {home_goals} from chances you'd expect to produce just {home_xg:.1f}")
            elif home_ratio > 1.3:
                lines.append(f"{home_team} taking their chances well with {home_goals} goals from limited opportunities")
            elif home_ratio < 0.5:
                lines.append(f"{home_team} will be frustrated — creating chances worth {home_xg:.1f} expected goals but only converting {home_goals}")
        
        if away_goals > 0 and away_xg > 0:
            away_ratio = away_goals / away_xg
            if away_ratio > 2:
                lines.append(f"{away_team} making the most of what they've got, {away_goals} goals from low-quality chances")
            elif away_ratio > 1.3:
                lines.append(f"{away_team} efficient in front of goal with {away_goals} scored")
            elif away_ratio < 0.5:
                lines.append(f"{away_team} guilty of missing chances, should have more than {away_goals}")
        
        if lines:
            insights.append({
                "category": "tactical",
                "line": "THE NUMBERS TELL THE STORY! " + ". ".join(lines) + "!",
                "facts_used": ["xG", "goals"]
            })
    
    # --- POSSESSION & CONTROL STORY ---
    home_pass = match_stats.get("avg_pass_accuracy_by_team", {}).get(home_team)
    away_pass = match_stats.get("avg_pass_accuracy_by_team", {}).get(away_team)
    home_pressure = match_stats.get("avg_pressure_index_by_team", {}).get(home_team)
    away_pressure = match_stats.get("avg_pressure_index_by_team", {}).get(away_team)
    
    if home_pass and away_pass and home_pressure and away_pressure:
        # Combine passing and pressing into one tactical narrative
        pass_leader = home_team if home_pass > away_pass else away_team
        press_leader = home_team if home_pressure > away_pressure else away_team
        pass_diff = abs(home_pass - away_pass)
        
        if pass_leader == press_leader:
            if pass_diff > 5:
                tactic_line = f"TOTAL CONTROL! {pass_leader} have dominated this game — sharper in possession ({home_pass}% vs {away_pass}%) AND pressing harder when they lose it!"
            else:
                tactic_line = f"{pass_leader} just edging the tactical battle — passing at {home_pass}% and pressing with more intensity throughout!"
        else:
            tactic_line = f"FASCINATING TACTICAL BATTLE! {pass_leader} sharper on the ball ({home_pass}% vs {away_pass}% passing) but {press_leader} winning the pressing duel and forcing mistakes!"
        
        insights.append({
            "category": "tactical",
            "line": tactic_line,
            "facts_used": ["pass_accuracy", "pressure_index"]
        })
    elif home_pass and away_pass:
        pass_diff = abs(home_pass - away_pass)
        if pass_diff > 5:
            leader = home_team if home_pass > away_pass else away_team
            insights.append({
                "category": "tactical",
                "line": f"THE TIDIER SIDE! {leader} have been far more composed in possession — {max(home_pass, away_pass):.0f}% pass accuracy vs {min(home_pass, away_pass):.0f}%!",
                "facts_used": ["pass_accuracy"]
            })
    
    # --- DISCIPLINE & DRAMA ---
    if match_stats.get("red_cards"):
        for red in match_stats["red_cards"]:
            mins_with_ten = minute - red["minute"]
            insights.append({
                "category": "milestone",
                "line": f"OFF! {red['player'].upper()} SAW RED AT {red['minute']}' — {red['team']} played the last {mins_with_ten} minutes with ten men! What drama!",
                "facts_used": ["red_cards"]
            })
    
    if match_stats.get("var_decisions_count", 0) > 0:
        var_count = match_stats["var_decisions_count"]
        if var_count == 1:
            insights.append({
                "category": "milestone",
                "line": "VAR INTERVENED TODAY — always a talking point and always controversial!",
                "facts_used": ["var_decisions"]
            })
        else:
            insights.append({
                "category": "milestone",
                "line": f"VAR HAS BEEN BUSY! {var_count} interventions today — what a controversial afternoon!",
                "facts_used": ["var_decisions"]
            })
    
    return insights

def generate_and_save_insight(fixture_id, processed, prompt, allowed_facts, editorial_ctx):
    try:
        logger.info(f"Generating AI insight for {fixture_id} | {processed.get('event_type')} at {processed.get('minute')}'")
        insight_result = generate_insights(prompt, allowed_facts, editorial_ctx)
        
        match_state = editorial_ctx.get("match_state")
        # Filter out duplicate insights
        used_lines = editorial_ctx.get("used_insights", [])
        filtered_insights = filter_duplicate_insights(
            insight_result["insights"],
            set(used_lines)
        )

        # Guarantee one player_stat line for player-driven moments (e.g., hat-tricks)
        filtered_insights = _ensure_player_stat_insight(filtered_insights, editorial_ctx, processed)
        
        # Only write if we have novel insights
        if filtered_insights:
            weight = _compute_editorial_weight(processed, editorial_ctx, match_state)
            write_insight(fixture_id, {
                "lead_story": insight_result["lead_story"],
                "insights": filtered_insights,
                "event_type": processed.get("event_type"),
                "player": processed.get("player"),
                "team": processed.get("team"),
                "opponent": processed.get("opponent"),
                "minute": processed.get("minute"),
                "score": processed.get("score"),
                "date": processed.get("date"),
                "editorial_weight": weight,
                "league": processed.get("league"),
                "xG": processed.get("xG"),
                "pass_accuracy": processed.get("pass_accuracy"),
                "pressure_index": processed.get("pressure_index"),
                "x": processed.get("x"),
                "y": processed.get("y"),
            })
        else:
            print(f"All insights for {fixture_id} were duplicates - skipped writing")
    except Exception as e:
        import traceback
        logger.error(f"AI insight generation failed for {fixture_id}, falling back to broadcaster: {e}")
        traceback.print_exc()
        # --- Fallback: broadcaster generator so the event is never lost ---
        try:
            match_state = editorial_ctx.get("match_state", {})
            event_type = processed.get("event_type", "").upper()
            broadcaster_lead = _broadcaster_lead(
                event_type, processed.get("player"), processed.get("team"),
                processed.get("opponent"), processed.get("score"), processed.get("minute"),
                match_state, editorial_ctx, processed,
            )
            broadcaster_insights = _broadcaster_insights(
                event_type, processed.get("player"), processed.get("team"),
                processed.get("opponent"), processed.get("score"), processed.get("minute"),
                match_state, editorial_ctx, {}, processed,
            )
            if not broadcaster_insights:
                broadcaster_insights = [{"category": "match_context", "line": broadcaster_lead}]
            weight = _compute_editorial_weight(processed, editorial_ctx, match_state)
            write_insight(fixture_id, {
                "lead_story": _sanitize(broadcaster_lead),
                "insights": [{**i, "line": _sanitize(i.get("line", ""))} for i in broadcaster_insights],
                "event_type": event_type,
                "player": processed.get("player"),
                "team": processed.get("team"),
                "opponent": processed.get("opponent"),
                "minute": processed.get("minute"),
                "score": processed.get("score"),
                "date": processed.get("date"),
                "editorial_weight": weight,
                "league": processed.get("league"),
                "xG": processed.get("xG"),
                "pass_accuracy": processed.get("pass_accuracy"),
                "pressure_index": processed.get("pressure_index"),
                "x": processed.get("x"),
                "y": processed.get("y"),
            })
            logger.info(f"Broadcaster fallback written for {fixture_id} | {event_type}")
        except Exception as fallback_err:
            logger.error(f"Broadcaster fallback also failed for {fixture_id}: {fallback_err}")

@app.post("/pubsub/push")
async def pubsub_push(request: Request, background_tasks: BackgroundTasks):
    envelope = await request.json()
    message = envelope.get("message", {})
    raw_data = message.get("data", "")
    message_id = message.get("messageId") or message.get("message_id")

    try:
        event_data = json.loads(base64.b64decode(raw_data).decode("utf-8"))
    except Exception:
        # Bad message — ack it so Pub/Sub doesn't retry garbage
        return JSONResponse(status_code=200, content={"status": "malformed_message_acked"})

    fixture_id = event_data.pop("fixture_id", _FIXTURE_ID)
    processed = process_event(event_data)

    if processed["status"] == "ignored":
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": processed["reason"]})

    # Pub/Sub dedup — skip if we've already processed this exact event
    dedup_key = _event_dedup_key(processed, message_id)
    if fixture_id not in _processed_events:
        _processed_events[fixture_id] = set()
    if dedup_key in _processed_events[fixture_id]:
        logger.info(f"Dedup: skipping {dedup_key} for {fixture_id}")
        return JSONResponse(status_code=200, content={"status": "duplicate_ignored"})
    _processed_events[fixture_id].add(dedup_key)

    # Layer 3 — pre-match stats from GCS (via sports_data which calls gcs_client)
    stats_context = get_context(processed)

    # Layer 2 — current match history from Firestore
    match_history = get_match_history(fixture_id)

    # Layer 1 — live match state (goals today, hat-tricks, etc.)
    match_state = build_match_state(match_history, processed)

    # Get previously shown insights for anti-repetition
    used_insight_lines = get_used_insight_lines(fixture_id)

    # Detect player performance milestones
    player_performance = None
    if processed.get("player"):
        player_performance = detect_player_performance(
            processed["player"], match_state, processed
        )

    # Build editorial context and prompt
    editorial_ctx = build_editorial_context(processed, stats_context)
    editorial_ctx["match_state"] = match_state
    editorial_ctx["player_performance"] = player_performance
    editorial_ctx["used_insights"] = list(used_insight_lines)[:20]  # Limit to prevent prompt bloat

    # Patch season_goals to include goals scored today (so 28 + 2 today = 30)
    if processed.get("player") and match_state:
        goals_today = match_state.get("goals_by_player", {}).get(processed["player"], 0)
        if goals_today > 0 and isinstance(editorial_ctx.get("player"), dict):
            base_sg = editorial_ctx["player"].get("season_goals")
            if base_sg is not None:
                editorial_ctx["player"]["season_goals"] = base_sg + goals_today

    # Persist event to match log BEFORE background task (so next events see it)
    append_match_event(fixture_id, processed)

    # Special handling for HALF_TIME and FULL_TIME - generate statistical summary
    event_type = processed.get("event_type", "").upper()
    local_mode = os.environ.get("DISABLE_FIRESTORE", "").strip().lower() in {"1", "true", "yes", "on"}
    ai_available = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))

    if event_type in {"HALF_TIME", "FULL_TIME"}:
        match_stats = build_match_statistics(match_history, processed)
        stat_insights = _build_match_summary_insights(match_stats, event_type, editorial_ctx)
        filtered_insights = filter_duplicate_insights(stat_insights, set())

        # Replace the plain lead with broadcaster voice
        broadcaster_lead = _broadcaster_lead(
            event_type, processed.get("player"), processed.get("team"),
            processed.get("opponent"), processed.get("score"), processed.get("minute"),
            match_state, editorial_ctx, processed,
        )
        # Upgrade the first (lead) insight line to broadcaster voice too
        if filtered_insights:
            filtered_insights[0]["line"] = _sanitize(broadcaster_lead)

        if filtered_insights:
            weight = _compute_editorial_weight(processed, editorial_ctx, match_state)
            write_insight(fixture_id, {
                "lead_story": _sanitize(broadcaster_lead),
                "insights": filtered_insights,
                "event_type": event_type,
                "player": None,
                "team": processed.get("team"),
                "opponent": processed.get("opponent"),
                "minute": processed.get("minute"),
                "score": processed.get("score"),
                "date": processed.get("date"),
                "editorial_weight": weight,
                "league": processed.get("league"),
                "xG": processed.get("xG"),
                "pass_accuracy": processed.get("pass_accuracy"),
                "pressure_index": processed.get("pressure_index"),
                "x": processed.get("x"),
                "y": processed.get("y"),
            })
        return JSONResponse(status_code=200, content={"status": "stats_generated"})

    # For all other events: use AI if available, else broadcaster stats generator
    if ai_available and not local_mode:
        prompt = build_insight_prompt(editorial_ctx, match_history=match_history)
        allowed_facts = flatten_for_grounding(editorial_ctx)
        background_tasks.add_task(generate_and_save_insight, fixture_id, processed, prompt, allowed_facts, editorial_ctx)
        return JSONResponse(status_code=200, content={"status": "processing_in_background"})

    # Local / no-AI path — broadcaster generator fires immediately
    broadcaster_lead = _broadcaster_lead(
        event_type, processed.get("player"), processed.get("team"),
        processed.get("opponent"), processed.get("score"), processed.get("minute"),
        match_state, editorial_ctx, processed,
    )
    broadcaster_insights = _broadcaster_insights(
        event_type, processed.get("player"), processed.get("team"),
        processed.get("opponent"), processed.get("score"), processed.get("minute"),
        match_state, editorial_ctx, stats_context, processed,
    )
    used_lines = list(get_used_insight_lines(fixture_id))
    filtered = filter_duplicate_insights(broadcaster_insights, set(used_lines))
    if not filtered:
        filtered = broadcaster_insights  # Always show something
    # Sanitize unicode before storing
    clean_lead = _sanitize(broadcaster_lead)
    clean_insights = [{**i, "line": _sanitize(i.get("line", ""))} for i in filtered]
    weight = _compute_editorial_weight(processed, editorial_ctx, match_state)
    write_insight(fixture_id, {
        "lead_story": clean_lead,
        "insights": clean_insights,
        "event_type": event_type,
        "player": processed.get("player"),
        "team": processed.get("team"),
        "opponent": processed.get("opponent"),
        "minute": processed.get("minute"),
        "score": processed.get("score"),
        "date": processed.get("date"),
        "editorial_weight": weight,
        "league": processed.get("league"),
        "xG": processed.get("xG"),
        "pass_accuracy": processed.get("pass_accuracy"),
        "pressure_index": processed.get("pressure_index"),
        "x": processed.get("x"),
        "y": processed.get("y"),
    })
    return JSONResponse(status_code=200, content={"status": "broadcaster_generated"})


# ---------------------------------------------------------------------------
# Dashboard — reads live insights from Firestore
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    insights = get_all_pending_insights()
    return templates.TemplateResponse("index.html", {"request": request, "insights": insights})


@app.get("/api/insights")
def api_insights():
    """JSON endpoint for the Next.js frontend to poll."""
    return get_all_pending_insights()


@app.get("/api/insights/stream")
async def api_insights_stream():
    """SSE endpoint — pushes insights only when Firestore data changes."""
    from fastapi.responses import StreamingResponse
    import asyncio as _aio

    start_insights_listener()

    async def event_generator():
        last_ids: set[str] = set()
        while True:
            data = await _aio.get_event_loop().run_in_executor(
                None, wait_for_snapshot_update, 25.0
            )
            current_ids = {d.get("id", "") for d in data}
            if current_ids != last_ids or not last_ids:
                last_ids = current_ids
                # Serialize datetime objects for JSON
                import json
                from datetime import datetime as _dt
                def _ser(obj):
                    if isinstance(obj, _dt):
                        return obj.isoformat()
                    raise TypeError(type(obj).__name__)
                payload = json.dumps(data, default=_ser)
                yield f"data: {payload}\n\n"
            else:
                yield ": heartbeat\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/clear")
def clear_dashboard():
    """Archive insights to training_data/ then clear all live collections and caches."""
    from gcs_data_store import reset_data_store
    from firestore_client import clear_mem_match_log

    # Always clear in-process caches regardless of mode
    _processed_events.clear()
    clear_mem_match_log()
    reset_data_store()

    local_mode = os.environ.get("DISABLE_FIRESTORE", "").strip().lower() in {"1", "true", "yes", "on"}
    if local_mode:
        clear_mem_insights()
        return {"status": "cleared", "message": "All caches and in-memory data cleared."}
    from clear_firestore import clear_all
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.environ.get("GCP_PROJECT", "avid-invention-484506-g9"))
    clear_all(db)
    return {"status": "cleared", "message": "All caches cleared. Firestore archived and wiped."}


# ---------------------------------------------------------------------------
# Historical Data page — test what the GCS CSV enrichment retrieves
# ---------------------------------------------------------------------------

@app.get("/historical-data", response_class=HTMLResponse)
def historical_data_page(request: Request):
    """Render a test page showing enriched CSV data from GCS for a given event."""
    from event_lookup import enrich_event
    from gcs_data_store import get_data_store

    params = dict(request.query_params)

    def _to_int(val):
        try: return int(val) if val and val not in ("None", "") else None
        except (ValueError, TypeError): return None

    def _to_float(val):
        try: return float(val) if val and val not in ("None", "") else None
        except (ValueError, TypeError): return None

    def _to_str(val):
        return val.replace("None", "").strip() or None if val else None

    query = {
        "player": params.get("player", "").replace("None", "").strip(),
        "team": params.get("team", "").replace("None", "").strip(),
        "opponent": params.get("opponent", "").replace("None", "").strip(),
        "date": params.get("date", "").replace("None", "").strip(),
        "event_type": params.get("event_type", "GOAL"),
        "fixture_id": params.get("fixture_id", "").replace("None", "").strip(),
        "minute": _to_int(params.get("minute")),
        "score": _to_str(params.get("score")),
        "pass_accuracy": _to_float(params.get("pass_accuracy")),
        "pressure_index": _to_int(params.get("pressure_index")),
        "xG": _to_float(params.get("xG")),
        "x": _to_float(params.get("x")),
        "y": _to_float(params.get("y")),
    }

    enriched = None
    raw_json = ""

    # Only run lookup if at least one field is populated
    if any([query["player"], query["team"], query["opponent"]]):
        event = {
            "event_type": query.get("event_type", ""),
            "player": query.get("player"),
            "team": query.get("team"),
            "opponent": query.get("opponent"),
            "date": query.get("date"),
            "minute": query.get("minute"),
            "score": query.get("score"),
            "pass_accuracy": query.get("pass_accuracy"),
            "pressure_index": query.get("pressure_index"),
            "xG": query.get("xG"),
            "x": query.get("x"),
            "y": query.get("y"),
        }
        try:
            store = get_data_store()
            enriched = enrich_event(event, store)
            raw_json = json.dumps(enriched, indent=2, default=str, ensure_ascii=False)
        except Exception as e:
            import traceback
            raw_json = f"ERROR: {e}\n\n{traceback.format_exc()}"

    return templates.TemplateResponse("historical_data.html", {
        "request": request,
        "query": query,
        "enriched": enriched,
        "raw_json": raw_json,
    })
