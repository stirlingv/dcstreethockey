"""
List every game that is in the past, isn't cancelled, and has no stats, and
work out from the rest of the schedule what probably happened to it.

Read-only. For each game it reports:

* whether the whole night for that division is missing stats (a rain-out
  looks like this; one forgotten scoresheet does not),
* whether the same two teams met again later in the season, and whether
  that later game was played (a rained-out game that was rescheduled),
* how many times the pair has played compared with the other pairs in the
  division (a pair that has already played as often as everyone else
  didn't need this game),
* anything typed into the game's notes.

From that it suggests one of: cancel (rescheduled), cancel (never played),
or look (stats may simply be missing). Nothing is changed; the suggestions
are for the admin's quick-cancel buttons.
"""

from collections import Counter, defaultdict
from datetime import date
from statistics import median

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from leagues.models import MatchUp
from leagues.seasons import active_season_ids

CANCEL_RESCHEDULED = "cancel: rescheduled"
CANCEL_NEVER_PLAYED = "cancel: never played"
LOOK = "look: stats may be missing"
RECENT = "wait: stats not entered yet"

# Scores are typed in the day after, sometimes a few days after, so a game
# this recent is not missing anything yet.
RECENT_DAYS = 7


def _pair(game):
    return tuple(sorted((game.hometeam_id, game.awayteam_id)))


def audit_unplayed_games(today=None, all_seasons=False):
    """The audit as data: a list of dicts, one per unplayed past game,
    oldest first. ``all_seasons`` looks beyond the seasons being played."""
    today = today or date.today()
    games = (
        MatchUp.objects.filter(week__date__lt=today)
        .select_related("hometeam", "awayteam", "week__division", "week__season")
        .annotate(stat_count=Count("stat"))
        .order_by("week__date", "week__division__division", "time", "pk")
    )
    if not all_seasons:
        games = games.filter(week__season_id__in=active_season_ids(today=today))
    games = list(games)

    # Everything about each season/division, played or not, in one pass.
    by_group = defaultdict(list)
    for game in games:
        by_group[(game.week.season_id, game.week.division_id)].append(game)
    later_games = defaultdict(list)  # (season, division, pair) -> games
    for group, members in by_group.items():
        for game in members:
            later_games[group + (_pair(game),)].append(game)

    rows = []
    for game in games:
        if game.stat_count or game.is_cancelled or game.week.is_cancelled:
            continue
        group = (game.week.season_id, game.week.division_id)
        members = by_group[group]
        night = [
            g for g in members if g.week.date == game.week.date and not g.is_cancelled
        ]
        night_played = sum(1 for g in night if g.stat_count)
        pair = _pair(game)
        later = [
            g
            for g in later_games[group + (pair,)]
            if g.week.date > game.week.date and not g.is_cancelled
        ]
        later_played = [g for g in later if g.stat_count]

        played_per_pair = Counter(
            _pair(g) for g in members if g.stat_count and not g.is_postseason
        )
        typical = median(played_per_pair.values()) if played_per_pair else 0
        pair_played = played_per_pair.get(pair, 0)

        whole_night_out = night_played == 0 and len(night) > 1
        if (today - game.week.date).days <= RECENT_DAYS:
            suggestion = RECENT
            why = f"played {(today - game.week.date).days} day(s) ago"
        elif later_played:
            suggestion = CANCEL_RESCHEDULED
            why = (
                f"{game.awayteam.team_name} and {game.hometeam.team_name} played "
                f"again on {later_played[0].week.date:%b %-d} and that game has "
                "stats"
            )
        elif whole_night_out:
            suggestion = CANCEL_NEVER_PLAYED
            why = (
                f"none of the {len(night)} {game.week.division} games that night "
                "has stats"
            )
        elif typical >= 2 and pair_played >= typical:
            # Only once the season is far enough along for "usual" to mean
            # something: every pair having met once proves nothing.
            suggestion = CANCEL_NEVER_PLAYED
            why = (
                f"the pair has already played {pair_played} game"
                f"{'s' if pair_played != 1 else ''}, the division's usual "
                f"{typical:g}"
            )
        else:
            suggestion = LOOK
            why = (
                f"{night_played} of {len(night)} games that night ha"
                f"{'s' if night_played == 1 else 've'} stats, and the pair has "
                f"played {pair_played} (usual {typical:g})"
            )
        if game.notes:
            why += f'; notes: "{game.notes.strip()}"'

        rows.append(
            {
                "game": game,
                "date": game.week.date,
                "division": str(game.week.division),
                "season": str(game.week.season),
                "matchup": f"{game.awayteam.team_name} at {game.hometeam.team_name}",
                "night_games": len(night),
                "night_played": night_played,
                "later_dates": [g.week.date for g in later],
                "later_played_dates": [g.week.date for g in later_played],
                "pair_played": pair_played,
                "typical_pair_played": typical,
                "notes": (game.notes or "").strip(),
                "suggestion": suggestion,
                "why": why,
            }
        )
    return rows


class Command(BaseCommand):
    help = (
        "List past games with no stats and say whether each looks rescheduled, "
        "never played, or simply missing its stats. Changes nothing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-seasons",
            action="store_true",
            help="Look at every season, not only the ones being played.",
        )

    def handle(self, *args, **options):
        rows = audit_unplayed_games(all_seasons=options["all_seasons"])
        if not rows:
            self.stdout.write("No past games are missing stats.")
            return
        current_date = None
        for row in rows:
            if row["date"] != current_date:
                current_date = row["date"]
                self.stdout.write("")
                self.stdout.write(
                    self.style.MIGRATE_HEADING(f"{current_date:%A, %B %-d, %Y}")
                )
            self.stdout.write(
                f"  [{row['game'].pk}] {row['division']} {row['game'].time:%-I:%M %p}"
                f"  {row['matchup']}"
            )
            self.stdout.write(f"      {row['suggestion']} — {row['why']}")
        self.stdout.write("")
        counts = Counter(row["suggestion"] for row in rows)
        self.stdout.write(self.style.MIGRATE_HEADING("Summary"))
        for suggestion in (CANCEL_RESCHEDULED, CANCEL_NEVER_PLAYED, LOOK, RECENT):
            self.stdout.write(f"  {counts.get(suggestion, 0):3d}  {suggestion}")
        self.stdout.write(f"  {len(rows):3d}  total")
