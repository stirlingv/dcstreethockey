from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, Http404, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.urls import reverse

from .models import (
    GoalieStatusChange,
    GoalieSubOffer,
    MatchUp,
    Team,
    Player,
    Roster,
    Week,
    PendingPlayerPhoto,
    PendingTeamPhoto,
)
from .forms import PlayerPhotoUploadForm, TeamPhotoUploadForm
from .goalie_board import (
    SIDES,
    client_ip,
    confirm_offer,
    confirm_side,
    games_needing_subs,
    goalie_sides_for_matchups,
    listed_goalies,
    notify_goalie_czar,
    over_rate_limit,
    resolve_person,
    side_fields,
)


def get_roster_goalie(team):
    """
    Get the primary goalie from a team's roster.
    Priority: 1) Primary goalie (is_primary_goalie=True)
              2) First non-substitute goalie (fallback)
    Checks both position1 and position2 for goalie position (4).
    """
    from django.db.models import Q

    # First try to find the designated primary goalie
    primary_entry = (
        Roster.objects.filter(
            team=team,
            is_substitute=False,
            is_primary_goalie=True,
        )
        .filter(Q(position1=4) | Q(position2=4))
        .select_related("player")
        .first()
    )
    if primary_entry:
        return primary_entry.player

    # Fallback: first non-substitute goalie (original behavior)
    roster_entry = (
        Roster.objects.filter(team=team, is_substitute=False)
        .filter(Q(position1=4) | Q(position2=4))
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
            "status_display": (
                matchup.get_away_goalie_status_display()
                if "away" in goalie_field
                else matchup.get_home_goalie_status_display()
            ),
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
            "status_display": (
                matchup.get_away_goalie_status_display()
                if "away" in goalie_field
                else matchup.get_home_goalie_status_display()
            ),
            "is_sub": is_sub,
            "is_roster_goalie": not is_sub,
        }
    else:
        # No explicit goalie - use roster goalie as default
        return {
            "goalie": roster_goalie,
            "goalie_name": (
                f"{roster_goalie.first_name} {roster_goalie.last_name}"
                if roster_goalie
                else "No goalie on roster"
            ),
            "status": status,
            "status_display": (
                matchup.get_away_goalie_status_display()
                if "away" in goalie_field
                else matchup.get_home_goalie_status_display()
            ),
            "is_sub": False,
            "is_roster_goalie": True,
        }


def goalie_status_board(request):
    """
    Public view showing goalie status for all upcoming matchups.
    """
    today = timezone.now().date()
    # Show all weeks for the next 4 upcoming dates, regardless of season.
    # This keeps overlapping season dates (e.g. championship + new season opener)
    # visible on the same board.
    upcoming_dates = list(
        Week.objects.filter(date__gte=today)
        .order_by("date")
        .values_list("date", flat=True)
        .distinct()[:4]
    )
    upcoming_weeks = (
        Week.objects.filter(date__in=upcoming_dates)
        .select_related("division", "season")
        .order_by(
            "date",
            "division__division",
            "-season__year",
            "season__season_type",
        )
    )

    upcoming_weeks = list(upcoming_weeks)
    all_matchups = list(
        MatchUp.objects.filter(week__in=upcoming_weeks)
        .select_related("week", "awayteam", "hometeam")
        .order_by("week__date", "time")
    )
    sides = goalie_sides_for_matchups(all_matchups)
    by_week = {}
    for matchup in all_matchups:
        by_week.setdefault(matchup.week_id, []).append(matchup)

    weeks_data = []
    # Goalies nobody has confirmed yet, for the nudge in the summary.
    # Cancelled games are listed but can't need a goalie.
    unconfirmed_count = 0
    for week in upcoming_weeks:
        matchups_data = []
        for matchup in by_week.get(week.id, []):
            info = sides[matchup.id]
            matchups_data.append(
                {
                    "matchup": matchup,
                    "away_goalie_info": info["away"],
                    "home_goalie_info": info["home"],
                    "sides": [info["away"], info["home"]],
                }
            )
            if matchup.is_cancelled:
                continue
            unconfirmed_count += sum(
                side["status"] == MatchUp.GOALIE_STATUS_UNCONFIRMED
                for side in (info["away"], info["home"])
            )
        weeks_data.append({"week": week, "matchups": matchups_data})

    context = {
        "weeks_data": weeks_data,
        # Named at the top with a link to each card, so the coordinator
        # doesn't scroll to find them.
        "sub_needed_games": games_needing_subs(all_matchups, sides),
        "unconfirmed_count": unconfirmed_count,
        "status_choices": MatchUp.GOALIE_STATUS_CHOICES,
        "goalie_choices": list(listed_goalies()),
        "czar_name": settings.GOALIE_CZAR_NAME,
    }
    return render(request, "leagues/goalie_status_board.html", context)


def _board_game(matchup_id, side):
    """The upcoming, uncancelled game and side a public board post targets."""
    if side not in SIDES:
        raise Http404("Unknown side")
    matchup = get_object_or_404(
        MatchUp.objects.select_related("week", "awayteam", "hometeam"),
        id=matchup_id,
    )
    if matchup.is_cancelled or matchup.week.date < timezone.now().date():
        raise Http404("This game is not open for goalie updates")
    return matchup


def _back_to_board(matchup):
    return redirect(f"{reverse('goalie_status_board')}#game-{matchup.id}")


def _clean(request, field, limit):
    return request.POST.get(field, "").strip()[:limit]


def _board_post_rejected(request, matchup, required, missing_message):
    """
    The checks every public board post goes through: the honeypot (bots fill
    every field, so a filled one is discarded silently), the per-address
    rate limit, and a required name. Returns a redirect to send back, or
    None when the post may go ahead.
    """
    if request.POST.get("website"):
        return _back_to_board(matchup)
    if over_rate_limit(request):
        messages.error(
            request,
            "Too many updates from your connection. Try again in a few minutes.",
        )
        return _back_to_board(matchup)
    if not required:
        messages.error(request, missing_message)
        return _back_to_board(matchup)
    return None


def _game_when(matchup):
    return f"{matchup.week.date:%A, %B %-d} at {matchup.time:%-I:%M %p}"


@require_POST
def confirm_goalie(request, matchup_id, side):
    """
    Public: on an Unconfirmed row, "Yes, confirmed" in one tap. On a Sub
    Needed row, "Select a goalie" names who's in goal: a volunteer, the
    roster goalie after all, another listed goalie, or someone new. The
    goalie, their captain, a teammate or the coordinator can do this, so the
    board asks about the goalie by name rather than assuming the tapper is
    the goalie. Open volunteers who weren't picked are told they're not
    needed.
    """
    matchup = _board_game(matchup_id, side)
    team_field, _, status_field = side_fields(side)
    team = getattr(matchup, team_field)

    rejected = _board_post_rejected(request, matchup, True, "")
    if rejected:
        return rejected

    choice = _clean(request, "goalie", 20) or "roster"
    goalie, goalie_name, released = confirm_side(
        matchup,
        side,
        choice,
        other_name=_clean(request, "goalie_name", 100),
        goalies=listed_goalies(),
    )
    info = goalie_sides_for_matchups([matchup])[matchup.id][side]
    reporter, name = resolve_person(request, info["roster"])
    GoalieStatusChange.objects.create(
        matchup=matchup,
        team=team,
        status=MatchUp.GOALIE_STATUS_CONFIRMED,
        goalie=goalie,
        reported_by=name,
        reported_by_player=reporter,
        note=f"Sub: {goalie_name}" if info["is_sub"] else "",
        source=GoalieStatusChange.SOURCE_BOARD,
        ip_address=client_ip(request),
    )
    who = goalie_name or f"{team.team_name}'s goalie"
    messages.success(
        request,
        f"Thanks{', ' + name if name else ''}. {who} is confirmed in goal for "
        f"{team.team_name} on {_game_when(matchup)}."
        + (
            f" {released} other volunteer{'s' if released != 1 else ''} marked not needed."
            if released
            else ""
        ),
    )
    return _back_to_board(matchup)


@require_POST
def report_sub_needed(request, matchup_id, side):
    """
    Public: anyone (a goalie, a captain, a teammate) can flag that a team
    needs a goalie sub for a game. Marks the side Sub Needed and, when the
    reporter picked their name from the roster or typed one, records who so
    the board shows "reported by". If they already have a sub lined up they
    can name them instead, and the game is confirmed with that sub in goal.
    """
    matchup = _board_game(matchup_id, side)
    team_field, goalie_field, status_field = side_fields(side)
    team = getattr(matchup, team_field)
    note = _clean(request, "note", 300)

    rejected = _board_post_rejected(request, matchup, True, "")
    if rejected:
        return rejected
    info = goalie_sides_for_matchups([matchup])[matchup.id][side]
    reporter, name = resolve_person(request, info["roster"])
    when = _game_when(matchup)

    sub_choice = _clean(request, "sub", 20)
    if sub_choice:
        goalie, goalie_name, _ = confirm_side(
            matchup,
            side,
            sub_choice,
            other_name=_clean(request, "sub_name", 100),
            goalies=listed_goalies(),
        )
        GoalieStatusChange.objects.create(
            matchup=matchup,
            team=team,
            status=MatchUp.GOALIE_STATUS_CONFIRMED,
            goalie=goalie,
            reported_by=name,
            reported_by_player=reporter,
            note=f"Sub: {goalie_name}" + (f". {note}" if note else ""),
            source=GoalieStatusChange.SOURCE_BOARD,
            ip_address=client_ip(request),
        )
        messages.success(
            request,
            f"Thanks{', ' + name if name else ''}. {goalie_name} is confirmed in "
            f"goal for {team.team_name} on {when} as a sub.",
        )
        return _back_to_board(matchup)

    setattr(matchup, goalie_field, None)
    setattr(matchup, status_field, MatchUp.GOALIE_STATUS_SUB_NEEDED)
    matchup.save()
    GoalieStatusChange.objects.create(
        matchup=matchup,
        team=team,
        status=MatchUp.GOALIE_STATUS_SUB_NEEDED,
        reported_by=name,
        reported_by_player=reporter,
        note=note,
        source=GoalieStatusChange.SOURCE_BOARD,
        ip_address=client_ip(request),
    )
    emailed = notify_goalie_czar(
        f"Goalie sub needed: {team.team_name} on {when}",
        f"{name or 'Someone'} reported that {team.team_name} needs a goalie sub on {when}"
        f" (vs {matchup.awayteam if team_field == 'hometeam' else matchup.hometeam})."
        f"{' Note: ' + note if note else ''}\n\n"
        f"Board: {request.build_absolute_uri(reverse('goalie_status_board'))}",
    )
    czar = settings.GOALIE_CZAR_NAME
    messages.success(
        request,
        f"Thanks{', ' + name if name else ''}. "
        f"{team.team_name} is now marked Sub Needed for {when}. "
        + (
            f"{czar} has been emailed."
            if emailed
            else f"{czar} and the captain can see it on the board."
        )
        + " Once a sub is lined up, tap “Select a goalie” on that game to put "
        "them in.",
    )
    return _back_to_board(matchup)


def captain_goalie_update(request, access_code):
    """
    Captain's view to update goalie status for their team's matchups.
    Authenticated via team's unique access code in the URL.
    """
    # Find the team by access code
    team = get_object_or_404(Team, captain_access_code=access_code, is_active=True)

    today = timezone.now().date()
    # Get upcoming matchups for this team based on date only — same approach
    # as goalie_status_board. Filtering by is_current_season is unreliable
    # because new seasons start with is_current_season=None.
    upcoming_matchups = (
        MatchUp.objects.filter(
            (Q(awayteam=team) | Q(hometeam=team)),
            week__date__gte=today,
        )
        .select_related("week", "awayteam", "hometeam", "away_goalie", "home_goalie")
        .order_by("week__date", "time")
    )

    # Get all goalies for the dropdown: players rostered as goalie on any team,
    # plus any player flagged can_play_goalie (e.g. a multi-position player who
    # occasionally fills in at goal but isn't officially rostered there).
    all_goalies = (
        Player.objects.filter(
            Q(roster__position1=4) | Q(roster__position2=4) | Q(can_play_goalie=True),
            is_active=True,
        )
        .distinct()
        .order_by("last_name", "first_name")
    )

    # Get team's roster goalie
    roster_goalie = get_roster_goalie(team)
    upcoming_matchups = list(upcoming_matchups)
    sides = goalie_sides_for_matchups(upcoming_matchups)

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
        side_info = sides[matchup.id]["home" if is_home else "away"]
        # A confirmed volunteer with no player record yet shows by name.
        sub_name = ""
        if side_info["goalie"] is None and side_info["goalie_name"]:
            display_goalie, sub_name = None, side_info["goalie_name"]

        matchups_data.append(
            {
                "matchup": matchup,
                "is_home": is_home,
                "opponent": opponent,
                "current_goalie": display_goalie,
                "sub_name": sub_name,
                "current_status": current_status,
                "roster_goalie": roster_goalie,
                "volunteers": side_info["volunteers"],
                "reported_by": side_info["reported_by"],
                "reported_at": side_info["reported_at"],
            }
        )

    context = {
        "team": team,
        "matchups_data": matchups_data,
        "all_goalies": all_goalies,
        "roster_goalie": roster_goalie,
        "status_choices": MatchUp.GOALIE_STATUS_CHOICES,
        "czar_name": settings.GOALIE_CZAR_NAME,
    }
    return render(request, "leagues/captain_goalie_update.html", context)


def _captain_offer(access_code, offer_id):
    team = get_object_or_404(Team, captain_access_code=access_code, is_active=True)
    offer = get_object_or_404(
        GoalieSubOffer.objects.select_related("matchup__week", "team"),
        id=offer_id,
        team=team,
    )
    return team, offer


@require_POST
def confirm_sub_offer(request, access_code, offer_id):
    """Captain: name a volunteer as the goalie and mark the game Confirmed."""
    team, offer = _captain_offer(access_code, offer_id)
    if offer.status != GoalieSubOffer.STATUS_OFFERED:
        messages.info(request, f"{offer.name}'s offer was already handled.")
    else:
        confirm_offer(
            offer,
            reported_by=f"{team.team_name} captain",
            source=GoalieStatusChange.SOURCE_CAPTAIN,
            ip=client_ip(request),
        )
        messages.success(
            request,
            f"{offer.name} is confirmed in goal for "
            f"{offer.matchup.week.date:%A, %B %-d}. Give them a call to lock it in.",
        )
    return redirect(
        f"{reverse('captain_goalie_update', args=[access_code])}#game-{offer.matchup_id}"
    )


@require_POST
def decline_sub_offer(request, access_code, offer_id):
    """Captain: pass on a volunteer (the game stays Sub Needed)."""
    team, offer = _captain_offer(access_code, offer_id)
    if offer.status == GoalieSubOffer.STATUS_OFFERED:
        offer.status = GoalieSubOffer.STATUS_DECLINED
        offer.save(update_fields=["status"])
        messages.success(request, f"Removed {offer.name} from the volunteers.")
    return redirect(
        f"{reverse('captain_goalie_update', args=[access_code])}#game-{offer.matchup_id}"
    )


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

    # If status is 2 (Sub Needed), goalie should be None
    if status == 2:
        goalie = None

    # Update the appropriate fields based on home/away
    if is_home:
        matchup.home_goalie = goalie
        matchup.home_goalie_status = status
    else:
        matchup.away_goalie = goalie
        matchup.away_goalie_status = status

    matchup.save()
    GoalieStatusChange.objects.create(
        matchup=matchup,
        team=team,
        status=status,
        goalie=goalie,
        reported_by=f"{team.team_name} captain",
        source=GoalieStatusChange.SOURCE_CAPTAIN,
        ip_address=client_ip(request),
    )
    if status == 2:
        when = f"{matchup.week.date:%A, %B %-d} at {matchup.time:%-I:%M %p}"
        notify_goalie_czar(
            f"Goalie sub needed: {team.team_name} on {when}",
            f"The {team.team_name} captain marked their game on {when} as Sub Needed.\n\n"
            f"Board: {request.build_absolute_uri(reverse('goalie_status_board'))}",
        )

    # Get updated display info
    roster_goalie = get_roster_goalie(team)
    display_goalie = goalie or roster_goalie

    # If status is 2, goalie_name should be blank
    goalie_name = ""
    is_sub = False
    if status != 2:
        goalie_name = (
            f"{display_goalie.first_name} {display_goalie.last_name}"
            if display_goalie
            else "No goalie"
        )
        is_sub = goalie is not None and roster_goalie and goalie.id != roster_goalie.id

    return JsonResponse(
        {
            "success": True,
            "goalie_name": goalie_name,
            "status": status,
            "status_display": dict(MatchUp.GOALIE_STATUS_CHOICES).get(
                status, "Unknown"
            ),
            "is_sub": is_sub,
        }
    )


def captain_urls_list(request):
    """
    Unlisted page showing captain goalie-update URLs for all active teams
    with at least one upcoming scheduled game.  No login required — the
    obscure URL is the only access control.
    """
    import datetime

    today = datetime.date.today()
    team_ids = {
        pk
        for pair in MatchUp.objects.filter(week__date__gte=today).values_list(
            "awayteam_id", "hometeam_id"
        )
        for pk in pair
    }
    teams = (
        Team.objects.filter(pk__in=team_ids, is_active=True)
        .select_related("season", "division")
        .order_by("division__division", "team_name")
    )

    # Group teams by division for the template.
    from collections import defaultdict

    grouped = defaultdict(list)
    for team in teams:
        captain_url = request.build_absolute_uri(
            f"/goalie-status/captain/{team.captain_access_code}/"
        )
        grouped[team.division].append(
            {
                "team": team,
                "captain_url": captain_url,
            }
        )
    # Sort divisions by their integer value.
    divisions = sorted(grouped.keys(), key=lambda d: d.division)
    groups = [(div, grouped[div]) for div in divisions]

    return render(
        request,
        "leagues/captain_urls_list.html",
        {
            "groups": groups,
            "total": len(team_ids),
        },
    )


def upload_player_photo(request, player_id):
    player = get_object_or_404(Player, id=player_id)

    if request.method == "POST":
        form = PlayerPhotoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Replace any existing pending submission for this player so old
            # files don't accumulate in storage.
            for old in player.pending_photos.all():
                old.photo.delete(save=False)
                old.delete()

            PendingPlayerPhoto.objects.create(
                player=player,
                photo=form.cleaned_data["photo"],
                submitter_email=form.cleaned_data.get("submitter_email", ""),
                submitter_note=form.cleaned_data.get("submitter_note", ""),
            )
            return render(
                request,
                "leagues/upload_player_photo.html",
                {"player": player, "submitted": True},
            )
    else:
        form = PlayerPhotoUploadForm()

    return render(
        request,
        "leagues/upload_player_photo.html",
        {"player": player, "form": form, "submitted": False},
    )


def upload_team_photo(request, team_id):
    team = get_object_or_404(Team, id=team_id)

    if request.method == "POST":
        form = TeamPhotoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Replace any existing pending submission for this team so old
            # files don't accumulate in storage.
            for old in team.pending_photos.all():
                old.photo.delete(save=False)
                old.delete()

            PendingTeamPhoto.objects.create(
                team=team,
                photo=form.cleaned_data["photo"],
                submitter_email=form.cleaned_data.get("submitter_email", ""),
                submitter_note=form.cleaned_data.get("submitter_note", ""),
            )
            return render(
                request,
                "leagues/upload_team_photo.html",
                {"team": team, "submitted": True},
            )
    else:
        form = TeamPhotoUploadForm()

    return render(
        request,
        "leagues/upload_team_photo.html",
        {"team": team, "form": form, "submitted": False},
    )
