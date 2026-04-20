from collections import defaultdict
from datetime import date, timedelta

from django import template

from leagues.models import MatchUp, Week

register = template.Library()


@register.inclusion_tag("admin/quick_cancel_widget.html", takes_context=True)
def quick_cancel_widget(context):
    today = date.today()
    cutoff = today + timedelta(days=7)

    upcoming_weeks = (
        Week.objects.filter(date__range=(today, cutoff))
        .select_related("division", "season")
        .order_by("date", "division__division", "pk")
    )

    # De-duplicate overlapping seasons: keep highest-pk week per (date, division).
    date_buckets = defaultdict(dict)  # {date: {division_id: week}}
    for week in upcoming_weeks:
        date_buckets[week.date][week.division_id] = week

    week_ids = [w.pk for d in date_buckets.values() for w in d.values()]
    matchups_by_week = defaultdict(list)
    for m in (
        MatchUp.objects.filter(week_id__in=week_ids, week__date__range=(today, cutoff))
        .select_related("hometeam", "awayteam")
        .order_by("time")
    ):
        matchups_by_week[m.week_id].append(m)

    grouped = {}
    for week_date in sorted(date_buckets.keys()):
        division_weeks = list(date_buckets[week_date].values())
        division_weeks.sort(key=lambda w: w.division.division)
        week_data = []
        for week in division_weeks:
            games = matchups_by_week[week.pk]
            all_c = all(g.is_cancelled for g in games) if games else week.is_cancelled
            any_c = any(g.is_cancelled for g in games) if games else week.is_cancelled
            week_data.append(
                {
                    "week": week,
                    "games": games,
                    "all_cancelled": all_c,
                    "any_cancelled": any_c,
                    "some_cancelled": any_c and not all_c,
                }
            )
        grouped[week_date] = {
            "divisions": week_data,
            "all_cancelled": all(d["all_cancelled"] for d in week_data),
            "any_cancelled": any(d["any_cancelled"] for d in week_data),
        }

    return {
        "grouped_weeks": grouped,
        "today": today,
        "csrf_token": context.get("csrf_token"),
    }
