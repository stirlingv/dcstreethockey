from django.contrib.admin import SimpleListFilter
from leagues.models import Week, Season


class RecentSeasonsFilter(SimpleListFilter):
    title = "season"
    parameter_name = "season"

    def lookups(self, request, model_admin):
        seasons = Season.objects.all().order_by("-year", "-season_type")[
            :5
        ]  # Limit to most recent 5 seasons
        lookups = [
            (season.id, f"{season.year} {season.get_season_type_display()}")
            for season in seasons
        ]
        lookups.append(("all", "All Seasons"))
        return lookups

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset
        elif self.value():
            return queryset.filter(week__season_id=self.value())
        return queryset.filter(
            week__season__in=Season.objects.all().order_by("-year", "-season_type")[:5]
        )


class CurrentSeasonWeekFilter(SimpleListFilter):
    title = "week"
    parameter_name = "week"

    def lookups(self, request, model_admin):
        current_season = Season.objects.filter(is_current_season=True).first()
        if current_season:
            weeks = Week.objects.filter(season=current_season).order_by("date")
            lookups = [(week.id, f"Week {week.id} - {week.date}") for week in weeks]
            lookups.append(("all", "All Weeks"))
            return lookups
        return []

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset
        elif self.value():
            return queryset.filter(week_id=self.value())
        current_season = Season.objects.filter(is_current_season=True).first()
        if current_season:
            return queryset.filter(week__season=current_season)
        return queryset


class MatchupDateFilter(SimpleListFilter):
    title = "matchup date"
    parameter_name = "week"

    def lookups(self, request, model_admin):
        current_season = Season.objects.filter(is_current_season=True).first()
        if current_season:
            weeks = Week.objects.filter(season=current_season).order_by("-date")
            lookups = [(week.id, f"Matchup Date: {week.date}") for week in weeks]
            lookups.append(("all", "All Matchup Dates"))
            return lookups
        return []

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset
        elif self.value():
            return queryset.filter(week_id=self.value())
        current_season = Season.objects.filter(is_current_season=True).first()
        if current_season:
            return queryset.filter(week__season=current_season)
        return queryset
