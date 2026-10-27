"""
Which season each division is playing, worked out from the schedule.

Nothing here reads ``Season.is_current_season``. That flag had to be set by
hand and went stale (sixteen seasons were still flagged current in 2026), so
the site now derives the answer from the games themselves:

* A division's **current** season is the oldest season that still has an
  unplayed, uncancelled game in that division. A season stays current until
  its last game, playoffs included, has been played. A rain-delayed
  championship therefore keeps its season current even when the next
  season's games have already started, and rescheduling that game is the
  only thing the admin has to do.
* With no games left to play, the current season is the newest one the
  division has played in.
* The **active** seasons are every division's current season plus any newer
  season that already has teams or games, so admin screens can show the
  season being scheduled next to the one being played.
"""

from datetime import date

from django.db.models import F

from leagues.models import Division, MatchUp, Season, Team, Week


def _season_key(year, season_type, season_id):
    """Sort key putting seasons in calendar order (Spring < Summer < ...)."""
    return (year or 0, season_type or 0, season_id)


def _pick(rows, newest):
    """``rows`` are (season_id, year, season_type) tuples."""
    rows = list(rows)
    if not rows:
        return None
    chosen = (max if newest else min)(rows, key=lambda r: _season_key(r[1], r[2], r[0]))
    return Season.objects.filter(pk=chosen[0]).first()


def current_season_for_division(division_id, today=None):
    """The season this division is playing right now, or None if it has
    never had a game scheduled."""
    if division_id is None:
        return None
    today = today or date.today()
    fields = ("week__season_id", "week__season__year", "week__season__season_type")
    remaining = (
        MatchUp.objects.filter(
            week__division_id=division_id,
            week__date__gte=today,
            is_cancelled=False,
        )
        .values_list(*fields)
        .distinct()
    )
    season = _pick(remaining, newest=False)
    if season is not None:
        return season
    played = (
        MatchUp.objects.filter(week__division_id=division_id)
        .values_list(*fields)
        .distinct()
    )
    return _pick(played, newest=True)


def current_seasons(today=None):
    """{division number: Season} for every division with a season."""
    result = {}
    for division in Division.objects.all():
        season = current_season_for_division(division.pk, today=today)
        if season is not None:
            result[division.division] = season
    return result


def current_season_ids(today=None):
    return {season.pk for season in current_seasons(today=today).values()}


def newest_season():
    """The most recent season that exists, whether or not it has games yet.
    This is the right default for a new team or an empty new week."""
    return Season.objects.order_by(
        F("year").desc(nulls_last=True),
        F("season_type").desc(nulls_last=True),
        "-pk",
    ).first()


def current_season(today=None):
    """One season for code that can only deal with one: the newest of the
    per-division current seasons, falling back to the newest season."""
    seasons = list(current_seasons(today=today).values())
    if seasons:
        return max(seasons, key=lambda s: _season_key(s.year, s.season_type, s.pk))
    return newest_season()


def active_season_ids(today=None):
    """Seasons being played or set up: each division's current season, plus
    any newer season that already has teams or scheduled games."""
    current = list(current_seasons(today=today).values())
    ids = {s.pk for s in current}
    if not current:
        newest = newest_season()
        return {newest.pk} if newest else set()
    oldest_key = min(_season_key(s.year, s.season_type, s.pk) for s in current)
    in_use = set(Team.objects.values_list("season_id", flat=True).distinct()) | set(
        Week.objects.values_list("season_id", flat=True).distinct()
    )
    for season in Season.objects.filter(pk__in=in_use):
        if _season_key(season.year, season.season_type, season.pk) > oldest_key:
            ids.add(season.pk)
    return ids


def season_for_new_week(division_id):
    """The season an empty new week in this division most likely belongs to:
    the newest season that has active teams in the division."""
    row = (
        Team.objects.filter(division_id=division_id, is_active=True)
        .exclude(season__isnull=True)
        .values_list("season_id", "season__year", "season__season_type")
        .distinct()
    )
    return _pick(row, newest=True) or newest_season()


def newest_active_season(today=None):
    """The newest of the active seasons: what a scheduling screen should
    open on, since that is the season being set up or played."""
    ids = active_season_ids(today=today)
    seasons = list(Season.objects.filter(pk__in=ids))
    if not seasons:
        return None
    return max(seasons, key=lambda s: _season_key(s.year, s.season_type, s.pk))
