"""
Goalie Status Board helpers shared by the public board, the captain page,
the schedule pages and the admin.

A game has two "sides" (away and home). Each side has a goalie status
(Confirmed / Sub Needed / Unconfirmed), an optional named goalie (a sub or
an explicit pick) and, when a sub is needed, any volunteers who offered
from the board.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from leagues.goalie_of_record import _roster_goalies
from leagues.models import GoalieStatusChange, GoalieSubOffer, MatchUp, Player, Roster

logger = logging.getLogger(__name__)

SIDES = ("away", "home")

# Public board posts allowed per address in the window (anti-spam, not auth).
RATE_LIMIT_POSTS = 10
RATE_LIMIT_WINDOW_SECONDS = 10 * 60


def side_fields(side):
    """Return (team field, goalie field, status field) for 'away' or 'home'."""
    if side not in SIDES:
        raise ValueError(f"unknown side {side!r}")
    return f"{side}team", f"{side}_goalie", f"{side}_goalie_status"


def full_name(player):
    return f"{player.first_name} {player.last_name}" if player else ""


def team_rosters(team_ids):
    """{team_id: [Player, ...]} of each team's active, non-substitute roster."""
    rosters = {}
    for entry in (
        Roster.objects.filter(
            team_id__in=team_ids,
            is_substitute=False,
            player__isnull=False,
            player__is_active=True,
        )
        .select_related("player")
        .order_by("player__last_name", "player__first_name")
    ):
        rosters.setdefault(entry.team_id, []).append(entry.player)
    return rosters


def goalie_sides_for_matchups(matchups):
    """
    Batched goalie info for many games: {matchup_id: {"away": info, "home": info}}.

    Each info dict has: team, goalie (Player or None), goalie_name, status,
    status_display, is_sub, needs_sub, volunteers (open GoalieSubOffer list),
    reported_by (name on the latest board/captain change, or ""),
    reported_at, roster (the team's players, for the "who's reporting?"
    picker), roster_goalie_name and prompt_name (the goalie the board's
    questions are about: "Is Pat Pads playing?", or "your goalie" when the
    team has nobody in goal on its roster).

    A confirmed volunteer the site has no Player for is shown by the name
    they gave, as a sub, until an admin links them to a player.
    """
    matchups = list(matchups)
    if not matchups:
        return {}
    team_ids = {m.awayteam_id for m in matchups} | {m.hometeam_id for m in matchups}
    roster_goalie_ids = _roster_goalies(team_ids)
    rosters = team_rosters(team_ids)
    needed_player_ids = set(roster_goalie_ids.values())
    for m in matchups:
        needed_player_ids.update(i for i in (m.away_goalie_id, m.home_goalie_id) if i)
    players = Player.objects.in_bulk(needed_player_ids) if needed_player_ids else {}

    matchup_ids = [m.id for m in matchups]
    offers = {}
    confirmed_unlinked = {}
    for offer in GoalieSubOffer.objects.filter(
        matchup_id__in=matchup_ids,
        status__in=(GoalieSubOffer.STATUS_OFFERED, GoalieSubOffer.STATUS_CONFIRMED),
    ).order_by("created_at"):
        key = (offer.matchup_id, offer.team_id)
        if offer.status == GoalieSubOffer.STATUS_OFFERED:
            offers.setdefault(key, []).append(offer)
        elif offer.player_id is None:
            confirmed_unlinked[key] = offer

    latest_change = {}
    for change in GoalieStatusChange.objects.filter(
        matchup_id__in=matchup_ids
    ).order_by("created_at"):
        latest_change[(change.matchup_id, change.team_id)] = change

    status_labels = dict(MatchUp.GOALIE_STATUS_CHOICES)
    result = {}
    for m in matchups:
        result[m.id] = {}
        for side in SIDES:
            team_field, goalie_field, status_field = side_fields(side)
            team = getattr(m, team_field)
            status = getattr(m, status_field)
            explicit_id = getattr(m, f"{goalie_field}_id")
            roster_id = roster_goalie_ids.get(team.id)
            needs_sub = status == MatchUp.GOALIE_STATUS_SUB_NEEDED
            goalie = None
            if not needs_sub:
                goalie = players.get(explicit_id or roster_id)
            is_sub = bool(explicit_id and roster_id and explicit_id != roster_id)
            goalie_name = full_name(goalie)
            unlinked = confirmed_unlinked.get((m.id, team.id))
            if (
                unlinked
                and explicit_id is None
                and status == MatchUp.GOALIE_STATUS_CONFIRMED
            ):
                goalie, goalie_name, is_sub = None, unlinked.name, True
            change = latest_change.get((m.id, team.id))
            # Only credit the report if it produced the status now shown.
            reported = change if change and change.status == status else None
            roster_goalie_name = full_name(players.get(roster_id))
            result[m.id][side] = {
                "side": side,
                "team": team,
                "goalie": goalie,
                "goalie_name": goalie_name,
                "roster_goalie_name": roster_goalie_name,
                "prompt_name": goalie_name or roster_goalie_name or "your goalie",
                "roster": rosters.get(team.id, []),
                "status": status,
                "status_display": status_labels.get(status, "Unknown"),
                "is_sub": is_sub,
                "needs_sub": needs_sub,
                "volunteers": offers.get((m.id, team.id), []),
                "reported_by": reported.reported_by if reported else "",
                "reported_at": reported.created_at if reported else None,
            }
    return result


def goalie_sides_for_matchup(matchup):
    return goalie_sides_for_matchups([matchup]).get(matchup.id, {})


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45] or None
    return request.META.get("REMOTE_ADDR") or None


def over_rate_limit(request):
    """Count this request against the address's window; True if over it."""
    ip = client_ip(request) or "unknown"
    key = f"goalie-board-posts:{ip}"
    count = cache.get(key, 0) + 1
    cache.set(key, count, RATE_LIMIT_WINDOW_SECONDS)
    return count > RATE_LIMIT_POSTS


def listed_goalies():
    """Players offered in the board's goalie pickers."""
    return (
        Player.objects.filter(
            Q(roster__position1=4) | Q(roster__position2=4) | Q(can_play_goalie=True),
            is_active=True,
        )
        .distinct()
        .order_by("last_name", "first_name")
    )


def resolve_person(request, candidates):
    """
    Who a board post says they are: (Player or None, display name).

    The form offers a picker of ``candidates`` (a team's roster, or the
    listed goalies) with a "someone else" option that reveals a text field.
    A picked id that isn't a candidate is ignored rather than trusted.
    """
    picked = request.POST.get("player_id", "").strip()
    if picked.isdigit():
        for player in candidates:
            if player.id == int(picked):
                return player, full_name(player)
    return None, request.POST.get("name", "").strip()[:100]


def offer_side(offer):
    matchup = offer.matchup
    return "home" if matchup.hometeam_id == offer.team_id else "away"


def _place_offer(offer):
    """
    Put a volunteer in goal: their side goes Confirmed, a volunteer the site
    knows is named as the game's goalie, one it doesn't is shown by the name
    they gave until an admin links them to a player (``link_offer_player``),
    so a typo never becomes a permanent player. Other open volunteers for
    that side are told they're not needed. Returns how many were released.
    """
    matchup = offer.matchup
    _, goalie_field, status_field = side_fields(offer_side(offer))
    if offer.player_id is not None:
        setattr(matchup, goalie_field, offer.player)
    setattr(matchup, status_field, MatchUp.GOALIE_STATUS_CONFIRMED)
    matchup.save()
    offer.status = GoalieSubOffer.STATUS_CONFIRMED
    offer.confirmed_at = timezone.now()
    offer.save()
    return (
        GoalieSubOffer.objects.filter(
            matchup=matchup,
            team_id=offer.team_id,
            status=GoalieSubOffer.STATUS_OFFERED,
        )
        .exclude(pk=offer.pk)
        .update(status=GoalieSubOffer.STATUS_DECLINED)
    )


def confirm_side(matchup, side, choice="roster", other_name="", goalies=()):
    """
    Mark one side of a game Confirmed with a chosen goalie in goal, from the
    board's "Select a goalie" picker or the "already found a sub" field:

    - "roster": the roster goalie plays (keeps a sub the captain already set).
    - "offer-<id>": one of the side's open volunteers.
    - "<player id>": a listed goalie (``goalies``); if they also volunteered,
      their offer is the one confirmed.
    - "other" with ``other_name``: a sub the site doesn't know, kept as a
      confirmed offer by name so nothing invents a player.

    Anything else behaves as "roster". Returns (goalie Player or None,
    goalie name shown on the board, released volunteer count).
    """
    team_field, goalie_field, status_field = side_fields(side)
    team_id = getattr(matchup, f"{team_field}_id")
    open_offers = GoalieSubOffer.objects.filter(
        matchup=matchup, team_id=team_id, status=GoalieSubOffer.STATUS_OFFERED
    )
    offer = None
    player = None
    if choice.startswith("offer-") and choice[6:].isdigit():
        offer = open_offers.filter(pk=int(choice[6:])).first()
    elif choice.isdigit():
        player = next((p for p in goalies if p.id == int(choice)), None)
        if player is not None:
            offer = open_offers.filter(player=player).first()
    elif choice == "other" and other_name:
        offer = GoalieSubOffer.objects.create(
            matchup=matchup, team_id=team_id, name=other_name[:100]
        )
    if offer is not None:
        offer.matchup = matchup  # update the caller's instance, not a fresh one
        released = _place_offer(offer)
        return offer.player, (full_name(offer.player) or offer.name), released
    if player is not None:
        setattr(matchup, goalie_field, player)
    setattr(matchup, status_field, MatchUp.GOALIE_STATUS_CONFIRMED)
    matchup.save()
    released = open_offers.update(status=GoalieSubOffer.STATUS_DECLINED)
    info = goalie_sides_for_matchups([matchup])[matchup.id][side]
    return info["goalie"], info["goalie_name"], released


def confirm_offer(offer, reported_by, source, ip=None):
    """A captain or admin confirms a volunteer: place them and log it."""
    matchup = offer.matchup
    _place_offer(offer)
    GoalieStatusChange.objects.create(
        matchup=matchup,
        team_id=offer.team_id,
        status=MatchUp.GOALIE_STATUS_CONFIRMED,
        goalie=offer.player,
        reported_by=reported_by,
        note=f"Confirmed volunteer {offer.name}",
        source=source,
        ip_address=ip,
    )


def link_offer_player(offer):
    """
    An admin linked a confirmed volunteer to a player: name that player as
    the game's goalie if nobody else has been named since.
    """
    if offer.status != GoalieSubOffer.STATUS_CONFIRMED or offer.player_id is None:
        return False
    matchup = offer.matchup
    _, goalie_field, status_field = side_fields(offer_side(offer))
    if getattr(matchup, f"{goalie_field}_id") is not None:
        return False
    setattr(matchup, goalie_field, offer.player)
    matchup.save()
    return True


def notify_goalie_czar(subject, body):
    """Email the goalie coordinator if an address is configured. Never raises."""
    to = getattr(settings, "GOALIE_CZAR_EMAIL", "")
    if not to:
        return False
    try:
        sent = send_mail(
            subject,
            body,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            [to],
            fail_silently=True,
        )
    except Exception:  # pragma: no cover - a misconfigured backend
        logger.exception("Could not email the goalie coordinator")
        return False
    return bool(sent)
