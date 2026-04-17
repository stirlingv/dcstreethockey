import datetime
from collections import defaultdict

from django.core.cache import cache
from django.templatetags.static import static

_CANCELLED_GAMES_CACHE_KEY = "cancelled_games_ctx"
_CANCELLED_GAMES_TTL = 30  # 30 seconds so cancellations propagate quickly


def jersey_path(request):
    return {"jersey_path": static("img/emojis/")}


def cancelled_games(request):
    result = cache.get(_CANCELLED_GAMES_CACHE_KEY)
    if result is None:
        from leagues.models import Week

        today = datetime.date.today()
        cancelled_weeks_qs = (
            Week.objects.filter(is_cancelled=True, date__gte=today)
            .select_related("division")
            .order_by("date", "division__division")
        )
        games = defaultdict(list)
        seen = set()  # deduplicate by (date, division_id)
        for week in cancelled_weeks_qs:
            key = (week.date, week.division_id)
            if key not in seen:
                seen.add(key)
                games[week.date].append(week.division.get_division_display())
        result = {"cancelled_games": dict(sorted(games.items()))}
        cache.set(_CANCELLED_GAMES_CACHE_KEY, result, _CANCELLED_GAMES_TTL)
    return result
