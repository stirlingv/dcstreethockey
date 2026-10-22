"""
Who played goal in a game, for goalie stat displays.

Each game has one Stat row per player, holding goals, assists, goals against
and empty-net goals against together. Nothing on the row says whether the
player was in net, so displays used to assume that a row with no goals and no
assists belongs to a goalie. That hid the rare game where a goalie records a
point: their goals against vanished from the box score and the game dropped
out of their goalie record.

A row now counts as a goalie appearance when either:

- it has no goals and no assists (the long-standing rule, which still covers
  sub goalies who were never named on the goalie status page), or
- the player is that team's goalie of record for the game.

The goalie of record follows the goalie status page: the goalie picked for
that team on the game, otherwise the team's roster goalie (the same default
the status page shows, see leagues.views.get_roster_goalie). When the status
is "Sub Needed" and no sub was named, there is no goalie of record.
"""

from django.db.models import Q

from leagues.models import MatchUp, Roster

SUB_NEEDED = 2


def _roster_goalies(team_ids):
    """
    {team_id: player_id} of each team's roster goalie, picked the same way as
    leagues.views.get_roster_goalie: the primary goalie first, otherwise the
    first non-substitute goalie by last name.
    """
    goalies = {}
    if not team_ids:
        return goalies
    rows = (
        Roster.objects.filter(team_id__in=team_ids, is_substitute=False)
        .filter(Q(position1=4) | Q(position2=4))
        .exclude(player__isnull=True)
        .order_by("team_id", "-is_primary_goalie", "player__last_name")
        .values_list("team_id", "player_id")
    )
    for team_id, player_id in rows:
        goalies.setdefault(team_id, player_id)
    return goalies


def goalies_of_record(matchups):
    """
    Map (matchup_id, team_id) to the player_id of each side's goalie of
    record. A side with no goalie of record is left out of the map.
    """
    sides = []
    for m in matchups:
        sides.append((m.id, m.hometeam_id, m.home_goalie_id, m.home_goalie_status))
        sides.append((m.id, m.awayteam_id, m.away_goalie_id, m.away_goalie_status))

    need_roster = {
        team_id
        for _, team_id, goalie_id, status in sides
        if team_id and goalie_id is None and status != SUB_NEEDED
    }
    roster_goalies = _roster_goalies(need_roster)

    result = {}
    for matchup_id, team_id, goalie_id, status in sides:
        if not team_id:
            continue
        if goalie_id is not None:
            result[(matchup_id, team_id)] = goalie_id
        elif status != SUB_NEEDED and team_id in roster_goalies:
            result[(matchup_id, team_id)] = roster_goalies[team_id]
    return result


def is_goalie_appearance(player_id, team_id, matchup_id, goals, assists, goalie_map):
    """True if this stat row should count as the player playing goal."""
    if not (goals or 0) and not (assists or 0):
        return True
    if matchup_id is None:
        return False
    return goalie_map.get((matchup_id, team_id)) == player_id


def goalie_appearance_ids(stat_qs):
    """IDs of the rows in ``stat_qs`` that count as goalie appearances."""
    rows = list(
        stat_qs.values("id", "player_id", "team_id", "matchup_id", "goals", "assists")
    )
    scoring_matchup_ids = {
        r["matchup_id"]
        for r in rows
        if r["matchup_id"] is not None and ((r["goals"] or 0) or (r["assists"] or 0))
    }
    goalie_map = (
        goalies_of_record(
            MatchUp.objects.filter(id__in=scoring_matchup_ids).only(
                "id",
                "hometeam",
                "awayteam",
                "home_goalie",
                "away_goalie",
                "home_goalie_status",
                "away_goalie_status",
            )
        )
        if scoring_matchup_ids
        else {}
    )
    return [
        r["id"]
        for r in rows
        if is_goalie_appearance(
            r["player_id"],
            r["team_id"],
            r["matchup_id"],
            r["goals"],
            r["assists"],
            goalie_map,
        )
    ]
