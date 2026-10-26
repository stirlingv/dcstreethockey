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
from leagues.models import GoalieStatusChange, GoalieSubOffer, MatchUp, Player

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


def goalie_sides_for_matchups(matchups):
    """
    Batched goalie info for many games: {matchup_id: {"away": info, "home": info}}.

    Each info dict has: team, goalie (Player or None), goalie_name, status,
    status_display, is_sub, needs_sub, volunteers (open GoalieSubOffer list),
    reported_by (name on the latest board/captain change, or ""), and
    reported_at.
    """
    matchups = list(matchups)
    if not matchups:
        return {}
    team_ids = {m.awayteam_id for m in matchups} | {m.hometeam_id for m in matchups}
    roster_goalie_ids = _roster_goalies(team_ids)
    needed_player_ids = set(roster_goalie_ids.values())
    for m in matchups:
        needed_player_ids.update(i for i in (m.away_goalie_id, m.home_goalie_id) if i)
    players = Player.objects.in_bulk(needed_player_ids) if needed_player_ids else {}

    matchup_ids = [m.id for m in matchups]
    offers = {}
    for offer in GoalieSubOffer.objects.filter(
        matchup_id__in=matchup_ids, status=GoalieSubOffer.STATUS_OFFERED
    ).order_by("created_at"):
        offers.setdefault((offer.matchup_id, offer.team_id), []).append(offer)

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
            change = latest_change.get((m.id, team.id))
            # Only credit the report if it produced the status now shown.
            reported = change if change and change.status == status else None
            result[m.id][side] = {
                "side": side,
                "team": team,
                "goalie": goalie,
                "goalie_name": (
                    f"{goalie.first_name} {goalie.last_name}" if goalie else ""
                ),
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
    """Players offered in the "I can sub" name suggestions and goalie pickers."""
    return (
        Player.objects.filter(
            Q(roster__position1=4) | Q(roster__position2=4) | Q(can_play_goalie=True),
            is_active=True,
        )
        .distinct()
        .order_by("last_name", "first_name")
    )


def match_listed_goalie(name):
    """The listed goalie whose full name matches ``name``, ignoring case."""
    parts = name.strip().split()
    if len(parts) < 2:
        return None
    first, last = parts[0], " ".join(parts[1:])
    return (
        listed_goalies()
        .filter(first_name__iexact=first, last_name__iexact=last)
        .first()
    )


def split_name(name):
    parts = name.strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def confirm_offer(offer, reported_by, source, ip=None):
    """
    Name the volunteer as the goalie for their side of the game and mark the
    game Confirmed. A volunteer the site didn't know becomes a player who
    can play goalie, so they can be picked again next time.
    """
    if offer.player_id is None:
        first, last = split_name(offer.name)
        offer.player = Player.objects.create(
            first_name=first, last_name=last or first, can_play_goalie=True
        )
    matchup = offer.matchup
    side = "home" if matchup.hometeam_id == offer.team_id else "away"
    _, goalie_field, status_field = side_fields(side)
    setattr(matchup, goalie_field, offer.player)
    setattr(matchup, status_field, MatchUp.GOALIE_STATUS_CONFIRMED)
    matchup.save()
    offer.status = GoalieSubOffer.STATUS_CONFIRMED
    offer.confirmed_at = timezone.now()
    offer.save()
    GoalieSubOffer.objects.filter(
        matchup=matchup, team_id=offer.team_id, status=GoalieSubOffer.STATUS_OFFERED
    ).exclude(pk=offer.pk).update(status=GoalieSubOffer.STATUS_DECLINED)
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
