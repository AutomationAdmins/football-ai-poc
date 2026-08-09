import base64
import json
import os

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
    record_decision,
    get_used_insight_lines,
)
from match_state_tracker import (
    build_match_state,
    detect_player_performance,
    filter_duplicate_insights,
    format_match_state_for_prompt,
    build_match_statistics,
)

_FIXTURE_ID = os.environ.get("FIXTURE_ID", "arsenal-vs-chelsea-2025-08-02")

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


def _build_match_summary_insights(match_stats: dict, event_type: str) -> list[dict]:
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
    
    # --- LEAD STORY: Narrative headline ---
    lead_parts = []
    
    # Who's winning and how?
    if home_goals > away_goals:
        margin = home_goals - away_goals
        if margin >= 3:
            lead_parts.append(f"{home_team} are dominant, leading {score} against {away_team}")
        elif margin == 2:
            lead_parts.append(f"{home_team} in control, leading {score} against {away_team}")
        else:
            lead_parts.append(f"{home_team} lead {score} against {away_team}")
    elif away_goals > home_goals:
        margin = away_goals - home_goals
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
                    line = f"{team} goal: {scorer_strs[0]}"
                else:
                    line = f"{team} with {goal_count} goals: {', '.join(scorer_strs)}"
                
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
                    "line": f"A match ball for {player} — {count} goals and a hat-trick to remember",
                    "facts_used": ["goals_by_player"]
                })
            elif count == 2:
                insights.append({
                    "category": "milestone",
                    "line": f"{player} with a brace — two goals and a real impact on this game",
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
                "line": ". ".join(lines),
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
            # Same team dominating both
            if pass_diff > 5:
                tactic_line = f"{pass_leader} have controlled this game — more accurate in possession ({home_pass}% vs {away_pass}%) and pressing harder when they lose it"
            else:
                tactic_line = f"{pass_leader} just about edging the tactical battle — passing at {home_pass}% accuracy and pressing with more intensity"
        else:
            # Different teams excelling in different areas
            tactic_line = f"{pass_leader} sharper on the ball ({home_pass}% vs {away_pass}% passing) but {press_leader} winning the pressing battle and forcing mistakes"
        
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
                "line": f"{leader} have been the tidier team in possession, passing at {max(home_pass, away_pass):.0f}% compared to {min(home_pass, away_pass):.0f}%",
                "facts_used": ["pass_accuracy"]
            })
    
    # --- DISCIPLINE & DRAMA ---
    if match_stats.get("red_cards"):
        for red in match_stats["red_cards"]:
            mins_with_ten = minute - red["minute"]
            insights.append({
                "category": "milestone",
                "line": f"{red['player']} saw red at {red['minute']}' — {red['team']} have played the last {mins_with_ten} minutes with ten men",
                "facts_used": ["red_cards"]
            })
    
    if match_stats.get("var_decisions_count", 0) > 0:
        var_count = match_stats["var_decisions_count"]
        if var_count == 1:
            insights.append({
                "category": "milestone",
                "line": "VAR has been involved once today — always a talking point",
                "facts_used": ["var_decisions"]
            })
        else:
            insights.append({
                "category": "milestone",
                "line": f"VAR has intervened {var_count} times — a controversial afternoon",
                "facts_used": ["var_decisions"]
            })
    
    return insights

def generate_and_save_insight(fixture_id, processed, prompt, allowed_facts, editorial_ctx):
    try:
        insight_result = generate_insights(prompt, allowed_facts, editorial_ctx)
        
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
            write_insight(fixture_id, {
                "lead_story": insight_result["lead_story"],
                "insights": filtered_insights,
                "event_type": processed.get("event_type"),
                "player": processed.get("player"),
                "team": processed.get("team"),
                "minute": processed.get("minute"),
                "score": processed.get("score"),
            })
        else:
            print(f"All insights for {fixture_id} were duplicates - skipped writing")
    except Exception as e:
        print(f"Error generating insight in background: {e}")

@app.post("/pubsub/push")
async def pubsub_push(request: Request, background_tasks: BackgroundTasks):
    envelope = await request.json()
    message = envelope.get("message", {})
    raw_data = message.get("data", "")

    try:
        event_data = json.loads(base64.b64decode(raw_data).decode("utf-8"))
    except Exception:
        # Bad message — ack it so Pub/Sub doesn't retry garbage
        return JSONResponse(status_code=200, content={"status": "malformed_message_acked"})

    fixture_id = event_data.pop("fixture_id", _FIXTURE_ID)
    processed = process_event(event_data)

    if processed["status"] == "ignored":
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": processed["reason"]})

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

    # Persist event to match log BEFORE background task (so next events see it)
    append_match_event(fixture_id, processed)

    # Special handling for HALF_TIME and FULL_TIME - generate statistical summary
    event_type = processed.get("event_type", "").upper()
    if event_type in {"HALF_TIME", "FULL_TIME"}:
        # Build comprehensive match statistics
        match_stats = build_match_statistics(match_history, processed)
        
        # Generate statistical insights
        stat_insights = _build_match_summary_insights(match_stats, event_type)
        
        # For HALF_TIME and FULL_TIME, only filter duplicates within the current insights
        # Don't filter against historical insights since these are summary moments
        filtered_insights = filter_duplicate_insights(stat_insights, set())
        
        # Write directly (no AI generation needed for stats)
        if filtered_insights:
            # Use the narrative lead story from the first insight
            narrative_lead = filtered_insights[0].get("line", f"{match_stats.get('home_team', 'Home')} {match_stats.get('score', '0-0')} {match_stats.get('away_team', 'Away')}")
            write_insight(fixture_id, {
                "lead_story": narrative_lead,
                "insights": filtered_insights,
                "event_type": event_type,
                "player": None,
                "team": processed.get("team"),
                "minute": processed.get("minute"),
                "score": processed.get("score"),
            })
        
        return JSONResponse(status_code=200, content={"status": "stats_generated"})
    
    # For other events, use AI generation
    prompt = build_insight_prompt(editorial_ctx, match_history=match_history)
    allowed_facts = flatten_for_grounding(editorial_ctx)

    # Persist AI insight asynchronously to avoid blocking the webhook
    background_tasks.add_task(generate_and_save_insight, fixture_id, processed, prompt, allowed_facts, editorial_ctx)

    return JSONResponse(status_code=200, content={"status": "processing_in_background"})


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


# ---------------------------------------------------------------------------
# Statistician decisions — approve / reject
# ---------------------------------------------------------------------------

@app.post("/decide/{fixture_id}/{insight_id}")
def decide(fixture_id: str, insight_id: str, request: Request):
    return JSONResponse(status_code=200, content={"status": "use_approve_or_reject"})


@app.post("/approve/{fixture_id}/{insight_id}")
def approve(fixture_id: str, insight_id: str):
    record_decision(fixture_id, insight_id, approved=True)
    return {"status": "approved", "fixture_id": fixture_id, "insight_id": insight_id}


@app.post("/reject/{fixture_id}/{insight_id}")
def reject(fixture_id: str, insight_id: str):
    record_decision(fixture_id, insight_id, approved=False)
    return {"status": "rejected", "fixture_id": fixture_id, "insight_id": insight_id}


@app.post("/api/clear")
def clear_dashboard():
    """Archive insights to training_data/ then clear all live collections."""
    from clear_firestore import clear_all
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.environ.get("GCP_PROJECT", "avid-invention-484506-g9"))
    clear_all(db)
    return {"status": "cleared", "message": "Insights archived to training_data and dashboard cleared."}
