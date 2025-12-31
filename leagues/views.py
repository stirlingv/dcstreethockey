from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, Http404, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from .models import MatchUp, Team, Player, Roster, Week, Season


def get_roster_goalie(team):
    """Get the primary (non-substitute) goalie from a team's roster."""
    roster_entry = (
        Roster.objects.filter(
            team=team, position1=4, is_substitute=False  # Goalie position
        )
        .select_related("player")
        .first()
    )
    return roster_entry.player if roster_entry else None


def get_goalie_display_info(matchup, team, goalie_field, status_field):
    """
    Get the goalie display info for a team in a matchup.
    Returns dict with goalie name, status, and whether it's the roster goalie.
    """
    goalie = getattr(matchup, goalie_field)
    status = getattr(matchup, status_field)
    roster_goalie = get_roster_goalie(team)

    # If status is 2 (Sub Needed), goalie name should be blank
    if status == 2:
        return {
            "goalie": None,
            "goalie_name": "",
            "status": status,
            "status_display": matchup.get_away_goalie_status_display()
            if "away" in goalie_field
            else matchup.get_home_goalie_status_display(),
            "is_sub": False,
            "is_roster_goalie": False,
        }
    if goalie:
        # Explicit goalie set (could be a sub)
        is_sub = roster_goalie and goalie.id != roster_goalie.id
        return {
            "goalie": goalie,
            "goalie_name": f"{goalie.first_name} {goalie.last_name}",
            "status": status,
            "status_display": matchup.get_away_goalie_status_display()
            if "away" in goalie_field
            else matchup.get_home_goalie_status_display(),
            "is_sub": is_sub,
            "is_roster_goalie": not is_sub,
        }
    else:
        # No explicit goalie - use roster goalie as default
        return {
            "goalie": roster_goalie,
            "goalie_name": f"{roster_goalie.first_name} {roster_goalie.last_name}"
            if roster_goalie
            else "No goalie on roster",
            "status": status,
            "status_display": matchup.get_away_goalie_status_display()
            if "away" in goalie_field
            else matchup.get_home_goalie_status_display(),
            "is_sub": False,
            "is_roster_goalie": True,
        }


def goalie_status_board(request):
    """
    Public view showing goalie status for all upcoming matchups.
    """
    today = timezone.now().date()

    # Get all current seasons
    current_seasons = Season.objects.filter(is_current_season=True)
    # Get upcoming weeks for all current seasons
    upcoming_weeks = (
        Week.objects.filter(date__gte=today, season__in=current_seasons)
        .order_by("date")
        .select_related("division", "season")[:4]
    )  # Next 4 weeks

    weeks_data = []
    for week in upcoming_weeks:
        matchups = (
            MatchUp.objects.filter(week=week)
            .select_related(
                "awayteam",
                "hometeam",
                "away_goalie",
                "home_goalie",
                "awayteam__division",
                "hometeam__division",
            )
            .order_by("time")
        )

        matchups_data = []
        for matchup in matchups:
            away_info = get_goalie_display_info(
                matchup, matchup.awayteam, "away_goalie", "away_goalie_status"
            )
            home_info = get_goalie_display_info(
                matchup, matchup.hometeam, "home_goalie", "home_goalie_status"
            )

            matchups_data.append(
                {
                    "matchup": matchup,
                    "away_goalie_info": away_info,
                    "home_goalie_info": home_info,
                }
            )

        weeks_data.append(
            {
                "week": week,
                "matchups": matchups_data,
            }
        )

    # Count games needing subs across all current seasons
    sub_needed_count = (
        MatchUp.objects.filter(week__date__gte=today, week__season__in=current_seasons)
        .filter(Q(away_goalie_status=2) | Q(home_goalie_status=2))
        .count()
    )

    context = {
        "weeks_data": weeks_data,
        "sub_needed_count": sub_needed_count,
        "status_choices": MatchUp.GOALIE_STATUS_CHOICES,
    }
    return render(request, "leagues/goalie_status_board.html", context)


def captain_goalie_update(request, access_code):
    """
    Captain's view to update goalie status for their team's matchups.
    Authenticated via team's unique access code in the URL.
    """
    # Find the team by access code
    team = get_object_or_404(Team, captain_access_code=access_code, is_active=True)

    today = timezone.now().date()
    current_seasons = Season.objects.filter(is_current_season=True)
    # Get upcoming matchups for this team in all current seasons
    upcoming_matchups = (
        MatchUp.objects.filter(
            (Q(awayteam=team) | Q(hometeam=team)),
            week__date__gte=today,
            week__season__in=current_seasons,
        )
        .select_related("week", "awayteam", "hometeam", "away_goalie", "home_goalie")
        .order_by("week__date", "time")
    )

    # Get all goalies for the dropdown (position1=4 means Goalie)
    all_goalies = (
        Player.objects.filter(Q(roster__position1=4) | Q(roster__position2=4))
        .distinct()
        .order_by("last_name", "first_name")
    )

    # Get team's roster goalie
    roster_goalie = get_roster_goalie(team)

    matchups_data = []
    for matchup in upcoming_matchups:
        is_home = matchup.hometeam_id == team.id
        opponent = matchup.awayteam if is_home else matchup.hometeam

        if is_home:
            current_goalie = matchup.home_goalie
            current_status = matchup.home_goalie_status
        else:
            current_goalie = matchup.away_goalie
            current_status = matchup.away_goalie_status

        # If no goalie explicitly set, use roster goalie as the "current"
        display_goalie = current_goalie or roster_goalie

        matchups_data.append(
            {
                "matchup": matchup,
                "is_home": is_home,
                "opponent": opponent,
                "current_goalie": display_goalie,
                "current_status": current_status,
                "roster_goalie": roster_goalie,
            }
        )

    context = {
        "team": team,
        "matchups_data": matchups_data,
        "all_goalies": all_goalies,
        "roster_goalie": roster_goalie,
        "status_choices": MatchUp.GOALIE_STATUS_CHOICES,
    }
    return render(request, "leagues/captain_goalie_update.html", context)


@require_POST
def update_goalie_status(request, access_code, matchup_id):
    """
    AJAX endpoint for captains to update goalie status.
    """
    team = get_object_or_404(Team, captain_access_code=access_code, is_active=True)
    matchup = get_object_or_404(MatchUp, id=matchup_id)

    # Verify this team is part of the matchup
    is_home = matchup.hometeam_id == team.id
    is_away = matchup.awayteam_id == team.id

    if not (is_home or is_away):
        return JsonResponse({"error": "Not authorized for this matchup"}, status=403)

    # Get the new values from the request
    goalie_id = request.POST.get("goalie_id")
    status = request.POST.get("status")

    try:
        status = int(status)
        if status not in [1, 2, 3]:
            raise ValueError("Invalid status")
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid status value"}, status=400)

    # Get the goalie (or None if using roster goalie)
    goalie = None
    if goalie_id and goalie_id != "roster":
        try:
            goalie = Player.objects.get(id=int(goalie_id))
        except (Player.DoesNotExist, ValueError):
            return JsonResponse({"error": "Invalid goalie"}, status=400)

    # Update the appropriate fields based on home/away
    if is_home:
        matchup.home_goalie = goalie
        matchup.home_goalie_status = status
    else:
        matchup.away_goalie = goalie
        matchup.away_goalie_status = status

    matchup.save()

    # Get updated display info
    roster_goalie = get_roster_goalie(team)
    display_goalie = goalie or roster_goalie

    return JsonResponse(
        {
            "success": True,
            "goalie_name": f"{display_goalie.first_name} {display_goalie.last_name}"
            if display_goalie
            else "No goalie",
            "status": status,
            "status_display": dict(MatchUp.GOALIE_STATUS_CHOICES).get(
                status, "Unknown"
            ),
            "is_sub": goalie is not None
            and roster_goalie
            and goalie.id != roster_goalie.id,
        }
    )
