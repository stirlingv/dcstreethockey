import datetime
from collections import defaultdict

from django.core.cache import cache
from django.db.models import Count
from django.templatetags.static import static

_CANCELLED_GAMES_CACHE_KEY = "cancelled_games_ctx"
_CANCELLED_GAMES_TTL = 30  # 30 seconds so cancellations propagate quickly


def jersey_path(request):
    return {"jersey_path": static("img/emojis/")}


def cancelled_games(request):
    result = cache.get(_CANCELLED_GAMES_CACHE_KEY)
    if result is None:
        from leagues.models import MatchUp

        today = datetime.date.today()
        cancelled_matchups = list(
            MatchUp.objects.filter(is_cancelled=True, week__date__gte=today)
            .select_related("week__division", "hometeam", "awayteam")
            .order_by("week__date", "week__division__division", "time")
        )

        if not cancelled_matchups:
            result = {"cancelled_games": {}}
            cache.set(_CANCELLED_GAMES_CACHE_KEY, result, _CANCELLED_GAMES_TTL)
            return result

        # Count all scheduled games on dates that have at least one cancellation.
        cancelled_dates = {m.week.date for m in cancelled_matchups}
        total_by_date = dict(
            MatchUp.objects.filter(week__date__in=cancelled_dates)
            .values("week__date")
            .annotate(n=Count("pk"))
            .values_list("week__date", "n")
        )

        # {date: {division_display: [matchup, ...]}}
        by_date = defaultdict(lambda: defaultdict(list))
        cancelled_count_by_date = defaultdict(int)
        for matchup in cancelled_matchups:
            division_name = matchup.week.division.get_division_display()
            by_date[matchup.week.date][division_name].append(matchup)
            cancelled_count_by_date[matchup.week.date] += 1

        result = {
            "cancelled_games": {
                d: {
                    "partial": cancelled_count_by_date[d]
                    < total_by_date.get(d, cancelled_count_by_date[d]),
                    "divisions": dict(divisions),
                }
                for d, divisions in sorted(by_date.items())
            }
        }
        cache.set(_CANCELLED_GAMES_CACHE_KEY, result, _CANCELLED_GAMES_TTL)
    return result
