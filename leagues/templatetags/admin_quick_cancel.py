from collections import defaultdict
from datetime import date, timedelta

from django import template

from leagues.models import Week

register = template.Library()


@register.inclusion_tag("admin/quick_cancel_widget.html", takes_context=True)
def quick_cancel_widget(context):
    today = date.today()
    # Show upcoming weeks across the next 90 days so the widget is always
    # visible even during gaps between seasons or when the next game is
    # further out than the current week.
    lookahead = today + timedelta(days=90)
    upcoming_weeks = (
        Week.objects.filter(date__range=(today, lookahead))
        .select_related("division", "season")
        .order_by("date", "division__division", "pk")
    )
    # If nothing in the next 90 days, fall back to the nearest future game
    # dates regardless of how far out they are (handles off-season gaps).
    if not upcoming_weeks.exists():
        future_dates = (
            Week.objects.filter(date__gt=today)
            .values_list("date", flat=True)
            .order_by("date")
            .distinct()[:3]
        )
        if future_dates:
            upcoming_weeks = (
                Week.objects.filter(date__in=list(future_dates))
                .select_related("division", "season")
                .order_by("date", "division__division", "pk")
            )

    date_buckets = defaultdict(dict)  # {date: {division_id: week}}
    for week in upcoming_weeks:
        # Keep the highest-pk week per (date, division) to handle seasons that
        # overlap on the same date. Order by pk ensures the last write wins.
        date_buckets[week.date][week.division_id] = week

    grouped = {}
    for week_date in sorted(date_buckets.keys()):
        weeks = list(date_buckets[week_date].values())
        # Re-sort by division number for consistent display order.
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
