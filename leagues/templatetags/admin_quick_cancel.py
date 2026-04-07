from collections import defaultdict
from datetime import date, timedelta

from django import template

from leagues.models import Week

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

    grouped = {}
    for week_date in sorted(date_buckets.keys()):
        weeks = list(date_buckets[week_date].values())
        weeks.sort(key=lambda w: w.division.division)
        grouped[week_date] = {
            "weeks": weeks,
            "all_cancelled": all(w.is_cancelled for w in weeks),
            "any_cancelled": any(w.is_cancelled for w in weeks),
        }

    return {
        "grouped_weeks": grouped,
        "today": today,
        "csrf_token": context.get("csrf_token"),
    }
