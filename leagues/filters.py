from django.contrib.admin import SimpleListFilter
from leagues.models import DraftSession, Week, Season, SeasonSignup


def _default_signup_season_id():
    """
    The season a commissioner most likely wants to see signups for:
    whichever one has signups open, falling back to the most recent
    draft season once signups close at the draw.
    """
    open_session = (
        DraftSession.objects.filter(signups_open=True)
        .order_by("-season__year", "-season__season_type")
        .first()
    )
    if open_session:
        return open_session.season_id

    latest = DraftSession.objects.order_by(
        "-season__year", "-season__season_type"
    ).first()
    return latest.season_id if latest else None


class SignupSeasonFilter(SimpleListFilter):
    """
    Season filter for draft signups that defaults to the open signup
    season instead of showing every season at once.

    Uses the `season__id__exact` parameter name so links built the plain
    Django way keep working.  "All Seasons" is an explicit choice rather
    than the absence of one — a bare URL means "use the default", so
    without it there would be no way to escape the default view.
    """

    title = "season"
    parameter_name = "season__id__exact"

    def lookups(self, request, model_admin):
        seasons = (
            Season.objects.filter(signups__isnull=False)
            .distinct()
            .order_by("-year", "-season_type")[:8]
        )
        return [(s.id, str(s)) for s in seasons] + [("all", "All Seasons")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "all":
            return queryset
        if value:
            return queryset.filter(season_id=value)
        default = _default_signup_season_id()
        if default:
            return queryset.filter(season_id=default)
        return queryset

    def choices(self, changelist):
        """
        Show the defaulted season as the selected one.

        SimpleListFilter would otherwise highlight "All" whenever no
        parameter is present, which would claim every season is listed
        while the queryset is actually scoped to one.
        """
        value = self.value()
        default = _default_signup_season_id()
        for pk, title in self.lookup_choices:
            if pk == "all":
                selected = value == "all"
            else:
                selected = str(value) == str(pk) or (value is None and default == pk)
            yield {
                "selected": selected,
                "query_string": changelist.get_query_string({self.parameter_name: pk}),
                "display": title,
            }


class BackupGoalieFilter(SimpleListFilter):
    """
    Signups who could fill in as a backup goalie: secondary position is
    Goalie, but primary position isn't (those already show up under the
    primary "signed up as goalie" count, so they're excluded here to
    avoid double-counting the same person in both groups).
    """

    title = "backup goalie"
    parameter_name = "backup_goalie"

    def lookups(self, request, model_admin):
        return (("yes", "Can fill in as backup"),)

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(
                secondary_position=SeasonSignup.POSITION_GOALIE
            ).exclude(primary_position=SeasonSignup.POSITION_GOALIE)
        return queryset


class CaptainInterestMultiFilter(SimpleListFilter):
    """
    Multi-select captain-interest filter.

    A commissioner reaching out to captain candidates often wants "Yes for
    sure" and "I can as I'm overdue" together in one view — a plain
    single-value filter forces two separate page loads to see each, and
    checkbox selections used for bulk actions (like copying emails) don't
    survive navigating to a new filtered page. Selecting multiple values
    here and clicking Apply gets the combined set in one shot instead.

    Reuses the same multi-select widget as the season filter below.
    """

    title = "captain interest"
    parameter_name = "captain_interest_ids"
    template = "admin/season_multiselect_filter.html"

    def __init__(self, request, params, model, model_admin):
        super().__init__(request, params, model, model_admin)
        self.request = request
        self.model_admin = model_admin

    def lookups(self, request, model_admin):
        return [
            (str(value), label)
            for value, label in SeasonSignup.CAPTAIN_INTEREST_CHOICES
        ]

    def _selected_values(self):
        if not self.value():
            return set()
        return {value for value in self.value().split(",") if value}

    def queryset(self, request, queryset):
        selected = self._selected_values()
        if selected:
            return queryset.filter(captain_interest__in=selected)
        return queryset

    def choices(self, changelist):
        selected = self._selected_values()
        base_query_string = changelist.get_query_string(remove=[self.parameter_name])
        options = [
            {"value": value, "display": label, "selected": value in selected}
            for value, label in self.lookups(self.request, self.model_admin)
        ]
        return [
            {
                "base_query_string": base_query_string,
                "options": options,
                "selected_ids": ",".join(sorted(selected)),
            }
        ]


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
