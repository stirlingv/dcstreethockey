# leagues/admin.py
from django import forms
from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.db import models
from django.db.models import Q, Max, Prefetch
from django.utils.http import urlencode
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse, path
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseRedirect
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

from dal import autocomplete
from .forms import MatchUpForm
from .fields import TwelveHourTimeField
from .widgets import Time12HourWidget
from leagues.models import (
    Division,
    Player,
    Team,
    Roster,
    Team_Stat,
    Week,
    MatchUp,
    MatchUpGoalieStatus,
    Stat,
    Ref,
    Season,
    HomePage,
    TeamPhoto,
    PlayerPhoto,
    PendingPlayerPhoto,
    SeasonSignup,
    DraftSession,
    DraftTeam,
    DraftRound,
    DraftPick,
)
import json
import logging
from datetime import timedelta, date

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom AdminSite — collapses draft models into a single "Setup Draft" entry
# on the admin home page, separate from the league management models.
# ---------------------------------------------------------------------------
_DRAFT_OBJECT_NAMES = frozenset({"DraftSession", "SeasonSignup", "DraftPick"})


class _DCHockeyAdminSite(admin.AdminSite):
    def each_context(self, request):
        context = super().each_context(request)
        context["pending_photo_count"] = PendingPlayerPhoto.objects.count()
        return context

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)

        # Only reorganize the full index page, not app-specific views
        if app_label is not None:
            return app_list

        leagues_app = next((a for a in app_list if a["app_label"] == "leagues"), None)
        if leagues_app is None:
            return app_list

        league_models = [
            m
            for m in leagues_app["models"]
            if m["object_name"] not in _DRAFT_OBJECT_NAMES
        ]
        leagues_app["models"] = league_models
        leagues_app["name"] = "League Management"

        draft_app = {
            "name": "Wednesday Draft",
            "app_label": "wednesday_draft",
            "app_url": "/admin/leagues/draftsession/draft-setup/",
            "has_module_perms": True,
            "models": [
                {
                    "name": "Setup Draft",
                    "object_name": "DraftSetup",
                    "perms": {
                        "add": False,
                        "change": True,
                        "delete": False,
                        "view": True,
                    },
                    "admin_url": "/admin/leagues/draftsession/draft-setup/",
                    "add_url": None,
                }
            ],
        }
        leagues_idx = app_list.index(leagues_app)
        app_list.insert(leagues_idx, draft_app)
        return app_list


def get_current_season():
    try:
        current_season_instance = Season.objects.filter(is_current_season=True).first()
        return current_season_instance
    except Season.DoesNotExist:
        return None


class SeasonMultiFilter(SimpleListFilter):
    title = "Season"
    parameter_name = "season_ids"
    template = "admin/season_multiselect_filter.html"

    def __init__(self, request, params, model, model_admin):
        super().__init__(request, params, model, model_admin)
        self.request = request
        self.model_admin = model_admin

    def lookups(self, request, model_admin):
        seasons = Season.objects.order_by("-year", "-season_type")
        return [
            (str(season.id), f"{season.year} {season.get_season_type_display()}")
            for season in seasons
        ]

    def _selected_ids(self):
        if not self.value():
            return set()
        return {value for value in self.value().split(",") if value}

    def queryset(self, request, queryset):
        selected = self._selected_ids()
        if selected:
            return queryset.filter(week__season_id__in=selected)
        return queryset

    def choices(self, changelist):
        selected = self._selected_ids()
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


def get_current_season_for_division(division_id):
    try:
        max_year = Season.objects.filter(team__division_id=division_id).aggregate(
            max_year=Max("year")
        )["max_year"]

        max_season_type = Season.objects.filter(
            team__division_id=division_id, year=max_year
        ).aggregate(max_season_type=Max("season_type"))["max_season_type"]

        current_season_instance = Season.objects.get(
            year=max_year, season_type=max_season_type
        )
        return current_season_instance
    except Season.DoesNotExist:
        return None


class RosterInlineForm(forms.ModelForm):
    class Meta:
        model = Roster
        fields = "__all__"
        widgets = {"player": autocomplete.ModelSelect2(url="player-autocomplete")}


class RosterInline(admin.TabularInline):
    model = Roster
    form = RosterInlineForm
    extra = 1
    fields = [
        "player",
        "position1",
        "position2",
        "player_number",
        "is_captain",
        "is_substitute",
        "is_primary_goalie",
    ]


class TeamStatInline(admin.TabularInline):
    model = Team_Stat
    extra = 1


class GoalieListFilter(SimpleListFilter):
    title = "Goalie"
    parameter_name = "is_goalie"

    def lookups(self, request, model_admin):
        return (("yes", "Goalies"),)

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(
                Q(roster__position1=4) | Q(roster__position2=4)
            ).distinct()
        return queryset


class MatchupTimeframeFilter(SimpleListFilter):
    title = "Timeframe"
    parameter_name = "timeframe"

    def lookups(self, request, model_admin):
        return (
            ("all", "All"),
            ("upcoming", "Upcoming"),
            ("past", "Past 30 days"),
            ("recent", "Last 30 days (past + upcoming)"),
        )

    def queryset(self, request, queryset):
        today = timezone.localdate()
        if self.value() == "all":
            return queryset
        if self.value() == "upcoming":
            return queryset.filter(week__date__gte=today)
        if self.value() == "past":
            return queryset.filter(
                week__date__lte=today,
                week__date__gte=today - timedelta(days=30),
            )
        if self.value() == "recent":
            return queryset.filter(week__date__gte=today - timedelta(days=30))
        return queryset


def _get_team_roster_goalie(team, prefetched_roster=None):
    """
    Get the primary goalie for a team.
    Priority: is_primary_goalie=True > first non-substitute goalie

    If prefetched_roster is provided, use it to avoid extra queries.
    """
    if not team:
        return None

    from django.db.models import Q

    # Use prefetched roster if available
    if prefetched_roster is not None:
        # Filter the prefetched list in Python (no DB query)
        goalies = [
            r
            for r in prefetched_roster
            if (r.position1 == 4 or r.position2 == 4) and not r.is_substitute
        ]
        # First look for primary goalie
        for roster in goalies:
            if roster.is_primary_goalie:
                return roster.player
        # Fallback to first goalie
        return goalies[0].player if goalies else None

    # Fallback to DB query if no prefetch (for non-list views)
    # First, try to find a primary goalie
    primary_roster = (
        Roster.objects.filter(
            team=team,
            is_primary_goalie=True,
            is_substitute=False,
        )
        .filter(Q(position1=4) | Q(position2=4))
        .select_related("player")
        .first()
    )
    if primary_roster:
        return primary_roster.player

    # Fallback: first non-substitute goalie
    roster_entry = (
        Roster.objects.filter(team=team, is_substitute=False)
        .filter(Q(position1=4) | Q(position2=4))
        .select_related("player")
        .first()
    )
    return roster_entry.player if roster_entry else None


def _apply_default_matchup_filters(request, default_timeframe="upcoming"):
    # Only skip the redirect when the user has already chosen a timeframe.
    # Having season_ids without a timeframe still needs a redirect so the
    # date filter is applied (otherwise future games surface at the top
    # when ordering is descending).
    if request.GET.get("timeframe"):
        return None
    query = request.GET.copy()
    query["timeframe"] = default_timeframe
    # Only inject default season_ids if the user hasn't already selected
    # seasons; preserves an explicit season choice made in the sidebar.
    if not query.get("season_ids"):
        current_seasons = Season.objects.filter(is_current_season=True)
        if current_seasons.exists():
            query["season_ids"] = ",".join(
                str(season_id)
                for season_id in current_seasons.values_list("id", flat=True)
            )
    return f"{request.path}?{query.urlencode()}"


class PlayerActiveFilter(SimpleListFilter):
    title = "Active Status"
    parameter_name = "is_active"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Active"),
            ("no", "Inactive"),
            ("protected", "Protected from auto-deactivation"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(is_active=True)
        if self.value() == "no":
            return queryset.filter(is_active=False)
        if self.value() == "protected":
            return queryset.filter(exclude_from_auto_deactivation=True)
        return queryset


class PlayerAdmin(admin.ModelAdmin):
    search_fields = ["last_name", "first_name"]
    list_select_related = ("player_photo",)
    list_filter = [GoalieListFilter, PlayerActiveFilter]
    list_display = ["__str__", "is_active", "exclude_from_auto_deactivation"]
    list_editable = ["is_active", "exclude_from_auto_deactivation"]


class StatInline(admin.TabularInline):
    model = Stat
    extra = 1

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        match_id = request.resolver_match.kwargs.get("object_id")
        if match_id:
            qs = qs.filter(matchup_id=match_id)
        return qs

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        match_id = request.resolver_match.kwargs.get("object_id")
        if db_field.name == "player" and match_id:
            try:
                match = MatchUp.objects.select_related("hometeam", "awayteam").get(
                    id=match_id
                )
                # Players on either roster for the two teams
                rostered_players = Player.objects.filter(
                    roster__team__in=[match.hometeam, match.awayteam]
                )
                # All active players who are a goalie in any roster
                goalie_players = Player.objects.filter(
                    Q(roster__position1=4) | Q(roster__position2=4),
                    is_active=True,
                )
                # Union of both querysets
                kwargs["queryset"] = (rostered_players | goalie_players).distinct()
            except MatchUp.DoesNotExist:
                kwargs["queryset"] = Player.objects.none()
        elif db_field.name == "team" and match_id:
            try:
                match = MatchUp.objects.select_related("hometeam", "awayteam").get(
                    id=match_id
                )
                kwargs["queryset"] = Team.objects.filter(
                    id__in=[match.hometeam.id, match.awayteam.id]
                )
            except MatchUp.DoesNotExist:
                kwargs["queryset"] = Team.objects.none()
        elif db_field.name == "matchup":
            # When editing an existing MatchUp, restrict the inline's matchup
            # dropdown to just this matchup so it doesn't load every game ever.
            if match_id:
                kwargs["queryset"] = MatchUp.objects.filter(id=match_id)
            else:
                kwargs["queryset"] = MatchUp.objects.none()
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

    # This method is called when saving each inline form
    def save_new(self, form, commit=True):
        stat = super().save_new(form, commit=False)
        player = stat.player
        team = stat.team
        season = team.season
        # Check if player is already on the roster for this team/season
        if not Roster.objects.filter(
            player=player, team=team, team__season=season
        ).exists():
            # You may want to let the admin choose position, but here we default to Goalie (4)
            Roster.objects.create(
                player=player,
                team=team,
                position1=4,  # Default to Goalie; adjust as needed
                is_substitute=True,
            )
        if commit:
            stat.save()
        return stat


class MatchUpAdmin(admin.ModelAdmin):
    """Admin for managing game logistics: times, dates, teams, refs, and stats."""

    form = MatchUpForm
    list_select_related = (
        "hometeam",
        "hometeam__season",
        "awayteam",
        "awayteam__season",
        "week",
        "week__season",
        "ref1",
        "ref2",
    )
    inlines = [
        StatInline,
    ]
    list_filter = (
        MatchupTimeframeFilter,
        "week__division",
        SeasonMultiFilter,
    )
    search_fields = [
        "awayteam__team_name",
        "hometeam__team_name",
    ]
    list_display = [
        "week",
        "formatted_time",
        "awayteam",
        "hometeam",
        "ref1",
        "ref2",
        "is_postseason",
    ]
    list_display_links = ["week", "formatted_time"]
    ordering = ["-week__date", "-time"]
    list_per_page = 50

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "week",
                    "time",
                    "awayteam",
                    "hometeam",
                    "ref1",
                    "ref2",
                    "notes",
                    "is_postseason",
                    "is_championship",
                )
            },
        ),
    )

    formfield_overrides = {
        models.TimeField: {
            "form_class": TwelveHourTimeField,
            "widget": Time12HourWidget,
        },
    }

    def formatted_time(self, obj):
        if obj.time:
            try:
                return obj.time.strftime("%I:%M %p")
            except ValueError:
                return obj.time
        return None

    formatted_time.short_description = "Time"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        division_id = request.GET.get("week__division__exact")

        if division_id and not request.GET.get("season_ids"):
            current_season_instance = get_current_season_for_division(division_id)
            if current_season_instance:
                qs = qs.filter(week__season=current_season_instance)
        return qs

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name in ["hometeam", "awayteam"]:
            kwargs["queryset"] = Team.objects.filter(is_active=True).select_related(
                "division", "season"
            )
        elif db_field.name == "week":
            matchup_id = request.resolver_match.kwargs.get("object_id")
            if matchup_id:
                try:
                    matchup = MatchUp.objects.select_related(
                        "week__season", "hometeam__division"
                    ).get(id=matchup_id)
                    kwargs["queryset"] = Week.objects.filter(
                        division=matchup.hometeam.division, season=matchup.week.season
                    ).select_related("season", "division")
                except MatchUp.DoesNotExist:
                    print("Could not find the matchup to filter weeks.")
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

    def render_change_list(self, request, *args, **kwargs):
        extra_context = kwargs.get("extra_context", {})
        recent_seasons = Season.objects.order_by("-year", "-season_type")[:5]
        extra_context["recent_seasons"] = recent_seasons
        kwargs["extra_context"] = extra_context
        return super().render_change_list(request, *args, **kwargs)

    # "Save and add another" creates a blank new matchup, which is never the
    # right action here (matchups are created via WeekAdmin). Remove it so the
    # only choices are "Save" (done → home) and "Save and continue editing".
    show_save_and_add_another = False

    def changelist_view(self, request, extra_context=None):
        redirect_url = _apply_default_matchup_filters(request, default_timeframe="past")
        if redirect_url:
            return redirect(redirect_url)
        return super().changelist_view(request, extra_context=extra_context)

    def response_post_save_change(self, request, obj):
        """After a plain 'Save', return to the admin home where the stats entry
        widget and quick-cancel widget live — not the matchup changelist."""
        return HttpResponseRedirect(reverse("admin:index"))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        try:
            match = MatchUp.objects.select_related("hometeam", "awayteam").get(
                pk=object_id
            )
            roster_entries = Roster.objects.filter(
                team__in=[match.hometeam_id, match.awayteam_id]
            ).values("player_id", "team_id")
            player_team_map = {
                str(r["player_id"]): str(r["team_id"]) for r in roster_entries
            }
            extra_context["player_team_map_json"] = json.dumps(player_team_map)
        except MatchUp.DoesNotExist:
            extra_context["player_team_map_json"] = "{}"
        return super().change_view(
            request, object_id, form_url=form_url, extra_context=extra_context
        )

    class Media:
        js = ("admin/js/stat_autofill_team.js",)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "schedule/",
                self.admin_site.admin_view(self.schedule_manager_view),
                name="leagues_matchup_schedule_manager",
            ),
        ]
        return custom_urls + urls

    def schedule_manager_view(self, request):
        import datetime as dt
        from collections import defaultdict as _defaultdict

        today = date.today()

        # ------------------------------------------------------------------ #
        # POST — save edits + create new matchups                             #
        # ------------------------------------------------------------------ #
        if request.method == "POST":
            division_id = request.POST.get("division_id", "")
            filter_date = request.POST.get("filter_date", "")
            updated = 0
            added = 0

            # --- Update existing matchups ---
            pks_raw = request.POST.get("matchup_pks", "")
            matchup_pks = [int(pk) for pk in pks_raw.split(",") if pk.strip().isdigit()]
            for matchup in MatchUp.objects.filter(pk__in=matchup_pks).select_related(
                "week__division", "week__season"
            ):
                new_date_str = request.POST.get(f"m_{matchup.pk}_date", "")
                new_time_str = request.POST.get(f"m_{matchup.pk}_time", "")
                changed = False

                if new_date_str:
                    try:
                        new_date_val = dt.datetime.strptime(
                            new_date_str, "%Y-%m-%d"
                        ).date()
                    except ValueError:
                        continue
                    if new_date_val != matchup.week.date:
                        week, _ = Week.objects.get_or_create(
                            division=matchup.week.division,
                            season=matchup.week.season,
                            date=new_date_val,
                            defaults={"is_cancelled": False},
                        )
                        matchup.week = week
                        changed = True

                if new_time_str:
                    try:
                        new_time_val = dt.datetime.strptime(
                            new_time_str, "%H:%M"
                        ).time()
                    except ValueError:
                        continue
                    if new_time_val != matchup.time:
                        matchup.time = new_time_val
                        changed = True

                if changed:
                    matchup.save()
                    updated += 1

            # --- Create new matchups ---
            new_row_count = int(request.POST.get("new_row_count", 0) or 0)
            for i in range(new_row_count):
                date_str = request.POST.get(f"new_{i}_date", "").strip()
                time_str = request.POST.get(f"new_{i}_time", "").strip()
                away_id = request.POST.get(f"new_{i}_away", "").strip()
                home_id = request.POST.get(f"new_{i}_home", "").strip()
                div_id = (
                    request.POST.get(f"new_{i}_division_id", "").strip() or division_id
                )
                if not all([date_str, time_str, away_id, home_id, div_id]):
                    continue
                try:
                    new_date_val = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
                    new_time_val = dt.datetime.strptime(time_str, "%H:%M").time()
                    away_team = Team.objects.get(pk=int(away_id))
                    home_team = Team.objects.get(pk=int(home_id))
                    division_obj = Division.objects.get(pk=int(div_id))
                except (ValueError, Team.DoesNotExist, Division.DoesNotExist):
                    continue
                season = (
                    get_current_season_for_division(division_obj.pk)
                    or get_current_season()
                )
                if not season:
                    continue
                week, _ = Week.objects.get_or_create(
                    division=division_obj,
                    season=season,
                    date=new_date_val,
                    defaults={"is_cancelled": False},
                )
                MatchUp.objects.create(
                    week=week,
                    time=new_time_val,
                    awayteam=away_team,
                    hometeam=home_team,
                )
                added += 1

            # Build result message
            parts = []
            if added:
                parts.append(f"{added} game{'s' if added != 1 else ''} added")
            if updated:
                parts.append(f"{updated} game{'s' if updated != 1 else ''} updated")
            if parts:
                messages.success(request, ", ".join(parts).capitalize() + ".")
            else:
                messages.info(request, "No changes were made.")

            params = {}
            if division_id:
                params["division_id"] = division_id
            if filter_date:
                params["filter_date"] = filter_date
            redirect_url = reverse("admin:leagues_matchup_schedule_manager")
            if params:
                redirect_url += "?" + urlencode(params)
            return HttpResponseRedirect(redirect_url)

        # ------------------------------------------------------------------ #
        # GET — render filter + table                                          #
        # ------------------------------------------------------------------ #
        division_id = request.GET.get("division_id", "")
        filter_date = request.GET.get("filter_date", "")

        all_divisions = (
            Division.objects.filter(week__date__gte=today)
            .distinct()
            .order_by("division")
        )

        matchups_by_date = {}
        matchup_pks_str = ""

        if division_id or filter_date:
            qs = (
                MatchUp.objects.filter(week__date__gte=today, is_cancelled=False)
                .select_related(
                    "hometeam", "awayteam", "week__division", "week__season"
                )
                .order_by("week__date", "time")
            )
            if division_id:
                qs = qs.filter(week__division_id=division_id)
            if filter_date:
                qs = qs.filter(week__date=filter_date)

            for m in qs:
                matchups_by_date.setdefault(m.week.date, []).append(m)
            matchup_pks_str = ",".join(
                str(m.pk) for games in matchups_by_date.values() for m in games
            )

        # Teams grouped by division — used by JS to populate add-row dropdowns
        teams_by_div = _defaultdict(list)
        for team in (
            Team.objects.filter(is_active=True)
            .select_related("division")
            .order_by("team_name")
        ):
            if team.division_id:
                teams_by_div[str(team.division_id)].append(
                    {"id": team.pk, "name": team.team_name}
                )

        context = {
            **self.admin_site.each_context(request),
            "title": "Manage Schedule",
            "all_divisions": all_divisions,
            "division_id": division_id,
            "filter_date": filter_date,
            "matchups_by_date": matchups_by_date,
            "matchup_pks_str": matchup_pks_str,
            "has_filters": bool(division_id or filter_date),
            "has_results": bool(matchups_by_date),
            "teams_by_division_json": json.dumps(dict(teams_by_div)),
            "division_names_json": json.dumps(
                {str(d.pk): str(d) for d in all_divisions}
            ),
            "opts": self.model._meta,
        }
        return render(request, "admin/leagues/matchup/schedule_manager.html", context)

    def lookup_allowed(self, lookup, value):
        if lookup in {"season_ids", "timeframe"}:
            return True
        return super().lookup_allowed(lookup, value)


class MatchUpGoalieStatusAdmin(admin.ModelAdmin):
    """
    Dedicated admin for managing goalie statuses.
    Optimized for quick goalie assignment and status updates.
    """

    list_select_related = (
        "hometeam",
        "hometeam__season",
        "awayteam",
        "awayteam__season",
        "week",
        "week__season",
        "away_goalie",
        "home_goalie",
    )
    list_filter = (
        MatchupTimeframeFilter,
        "week__division",
        SeasonMultiFilter,
        "away_goalie_status",
        "home_goalie_status",
    )
    search_fields = [
        "awayteam__team_name",
        "hometeam__team_name",
        "away_goalie__first_name",
        "away_goalie__last_name",
        "home_goalie__first_name",
        "home_goalie__last_name",
    ]
    list_display = [
        "week",
        "formatted_time",
        "awayteam",
        "away_goalie",
        "away_goalie_status",
        "hometeam",
        "home_goalie",
        "home_goalie_status",
    ]
    list_editable = [
        "away_goalie",
        "away_goalie_status",
        "home_goalie",
        "home_goalie_status",
    ]
    list_display_links = ["week", "formatted_time"]
    ordering = ["week__date", "time"]
    list_per_page = 50

    fieldsets = (
        (
            "Match Info (Read Only)",
            {
                "fields": ("week", "time", "awayteam", "hometeam"),
                "classes": ("collapse",),
            },
        ),
        (
            "Away Team Goalie",
            {
                "fields": ("away_goalie", "away_goalie_status"),
            },
        ),
        (
            "Home Team Goalie",
            {
                "fields": ("home_goalie", "home_goalie_status"),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        # Make match info read-only since this admin is just for goalie status
        return ["week", "time", "awayteam", "hometeam"]

    def has_add_permission(self, request):
        # Don't allow adding matchups from this admin - use main MatchUp admin
        return False

    def has_delete_permission(self, request, obj=None):
        # Don't allow deleting matchups from this admin
        return False

    def away_goalie_status_display(self, obj):
        status_colors = {1: "green", 2: "red", 3: "orange"}
        status = obj.away_goalie_status
        color = status_colors.get(status, "gray")
        label = obj.get_away_goalie_status_display()
        return format_html('<span style="color: {};">{}</span>', color, label)

    away_goalie_status_display.short_description = "Away Goalie"
    away_goalie_status_display.admin_order_field = "away_goalie_status"

    def home_goalie_status_display(self, obj):
        status_colors = {1: "green", 2: "red", 3: "orange"}
        status = obj.home_goalie_status
        color = status_colors.get(status, "gray")
        label = obj.get_home_goalie_status_display()
        return format_html('<span style="color: {};">{}</span>', color, label)

    home_goalie_status_display.short_description = "Home Goalie"
    home_goalie_status_display.admin_order_field = "home_goalie_status"

    def formatted_time(self, obj):
        if obj.time:
            try:
                return obj.time.strftime("%I:%M %p")
            except ValueError:
                return obj.time
        return None

    formatted_time.short_description = "Time"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        division_id = request.GET.get("week__division__exact")

        if division_id and not request.GET.get("season_ids"):
            current_season_instance = get_current_season_for_division(division_id)
            if current_season_instance:
                qs = qs.filter(week__season=current_season_instance)

        goalie_roster = Prefetch(
            "roster_set",
            queryset=Roster.objects.filter(
                Q(position1=4) | Q(position2=4), is_substitute=False
            ).select_related("player"),
        )
        qs = qs.prefetch_related(
            Prefetch("awayteam__roster_set", queryset=goalie_roster.queryset),
            Prefetch("hometeam__roster_set", queryset=goalie_roster.queryset),
        )
        return qs

    def _get_goalie_queryset(self):
        """Get the filtered queryset of goalies for dropdown fields."""
        from datetime import date

        current_year = date.today().year
        recent_years = [current_year, current_year - 1, current_year - 2]

        # Use a subquery approach for better performance
        goalie_player_ids = Roster.objects.filter(
            Q(position1=4) | Q(position2=4)
        ).values_list("player_id", flat=True)

        return (
            Player.objects.filter(id__in=goalie_player_ids)
            .filter(Q(is_active=True) | Q(roster__team__season__year__in=recent_years))
            .distinct()
            .order_by("last_name", "first_name")
        )

    def get_changelist_form(self, request, **kwargs):
        # Cache goalie choices on the request to avoid re-querying
        if not hasattr(request, "_goalie_choices_cache"):
            goalie_qs = self._get_goalie_queryset()
            # Evaluate queryset once and cache as list of tuples
            request._goalie_choices_cache = [("", "---------")] + [
                (p.pk, str(p)) for p in goalie_qs
            ]

        goalie_choices = request._goalie_choices_cache
        list_editable_fields = list(self.list_editable)

        class MatchUpGoalieForm(forms.ModelForm):
            away_goalie = forms.ChoiceField(
                choices=goalie_choices,
                required=False,
                label="Away Goalie",
            )
            home_goalie = forms.ChoiceField(
                choices=goalie_choices,
                required=False,
                label="Home Goalie",
            )

            class Meta:
                model = MatchUpGoalieStatus
                fields = list_editable_fields

            def clean_away_goalie(self):
                value = self.cleaned_data.get("away_goalie")
                if value == "" or value is None:
                    return None
                return Player.objects.get(pk=value)

            def clean_home_goalie(self):
                value = self.cleaned_data.get("home_goalie")
                if value == "" or value is None:
                    return None
                return Player.objects.get(pk=value)

        return MatchUpGoalieForm

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name in ["away_goalie", "home_goalie"]:
            kwargs["queryset"] = self._get_goalie_queryset()
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

    def get_changelist_formset(self, request, **kwargs):
        from django.forms.models import BaseModelFormSet

        class MatchUpGoalieFormSet(BaseModelFormSet):
            def _construct_form(self, i, **form_kwargs):
                form = super()._construct_form(i, **form_kwargs)
                instance = getattr(form, "instance", None)
                if not instance:
                    return form
                away_roster_goalie = None
                home_roster_goalie = None
                # Use prefetched roster data to avoid N+1 queries
                if instance.awayteam_id:
                    prefetched_away = getattr(
                        instance.awayteam, "_prefetched_objects_cache", {}
                    ).get("roster_set")
                    if prefetched_away is not None:
                        away_roster_goalie = _get_team_roster_goalie(
                            instance.awayteam, prefetched_roster=list(prefetched_away)
                        )
                    else:
                        away_roster_goalie = _get_team_roster_goalie(instance.awayteam)
                    form.fields["away_goalie"].widget.attrs["data-roster-goalie-id"] = (
                        str(away_roster_goalie.pk) if away_roster_goalie else ""
                    )
                if instance.hometeam_id:
                    prefetched_home = getattr(
                        instance.hometeam, "_prefetched_objects_cache", {}
                    ).get("roster_set")
                    if prefetched_home is not None:
                        home_roster_goalie = _get_team_roster_goalie(
                            instance.hometeam, prefetched_roster=list(prefetched_home)
                        )
                    else:
                        home_roster_goalie = _get_team_roster_goalie(instance.hometeam)
                    form.fields["home_goalie"].widget.attrs["data-roster-goalie-id"] = (
                        str(home_roster_goalie.pk) if home_roster_goalie else ""
                    )

                # Set initial values for ChoiceField (needs to be pk, not object)
                if instance.away_goalie_id:
                    form.initial["away_goalie"] = instance.away_goalie_id
                elif (
                    instance.away_goalie_status == 3
                    and instance.awayteam_id
                    and away_roster_goalie
                ):
                    form.initial["away_goalie"] = away_roster_goalie.pk

                if instance.home_goalie_id:
                    form.initial["home_goalie"] = instance.home_goalie_id
                elif (
                    instance.home_goalie_status == 3
                    and instance.hometeam_id
                    and home_roster_goalie
                ):
                    form.initial["home_goalie"] = home_roster_goalie.pk

                return form

        kwargs["formset"] = MatchUpGoalieFormSet
        return super().get_changelist_formset(request, **kwargs)

    class Media:
        js = ("admin/js/goalie_status_admin.js",)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "add-goalie-sub/",
                self.admin_site.admin_view(self.add_goalie_sub_view),
                name="leagues_matchupgoaliestatus_add_goalie_sub",
            ),
        ]
        return custom_urls + urls

    def add_goalie_sub_view(self, request):
        """Custom view to add a new goalie sub (Player + Roster entry)."""
        from .models import Team

        class AddGoalieSubForm(forms.Form):
            first_name = forms.CharField(max_length=100)
            last_name = forms.CharField(max_length=100)
            team = forms.ModelChoiceField(
                queryset=Team.objects.filter(is_active=True).select_related(
                    "division", "season"
                ),
                required=True,
                help_text="Team to add the goalie sub to",
            )
            email = forms.EmailField(required=False)

        if request.method == "POST":
            form = AddGoalieSubForm(request.POST)
            if form.is_valid():
                # Create the player
                player = Player.objects.create(
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    email=form.cleaned_data["email"] or None,
                    is_active=True,
                )
                # Create roster entry as substitute goalie
                team = form.cleaned_data["team"]
                Roster.objects.create(
                    player=player,
                    team=team,
                    position1=4,  # Goalie position
                    is_substitute=True,
                )
                messages.success(
                    request,
                    f"Successfully added {player.first_name} {player.last_name} as a goalie sub for {team}.",
                )
                # Redirect back to goalie status list with preserved filters
                redirect_url = reverse("admin:leagues_matchupgoaliestatus_changelist")
                if request.GET.get("_popup"):
                    return render(
                        request,
                        "admin/leagues/matchupgoaliestatus/add_goalie_sub_done.html",
                        {"player": player},
                    )
                return HttpResponseRedirect(redirect_url)
        else:
            form = AddGoalieSubForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Add Goalie Sub",
            "form": form,
            "opts": self.model._meta,
            "is_popup": request.GET.get("_popup"),
        }
        return render(
            request, "admin/leagues/matchupgoaliestatus/add_goalie_sub.html", context
        )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["add_goalie_sub_url"] = reverse(
            "admin:leagues_matchupgoaliestatus_add_goalie_sub"
        )
        redirect_url = _apply_default_matchup_filters(request)
        if redirect_url:
            return redirect(redirect_url)
        return super().changelist_view(request, extra_context=extra_context)

    def render_change_list(self, request, *args, **kwargs):
        extra_context = kwargs.get("extra_context", {})
        recent_seasons = Season.objects.order_by("-year", "-season_type")[:5]
        extra_context["recent_seasons"] = recent_seasons
        kwargs["extra_context"] = extra_context
        return super().render_change_list(request, *args, **kwargs)

    def lookup_allowed(self, lookup, value):
        if lookup in {"season_ids", "timeframe"}:
            return True
        return super().lookup_allowed(lookup, value)


class MatchUpInline(admin.TabularInline):
    model = MatchUp
    form = MatchUpForm
    extra = 4
    raw_id_fields = ["awayteam", "hometeam"]

    formfield_overrides = {
        models.TimeField: {
            "form_class": TwelveHourTimeField,
            "widget": Time12HourWidget,
        },
    }

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Get the week_id from the URL parameters
        week_id = request.resolver_match.kwargs.get("object_id")
        if week_id:
            qs = qs.filter(week_id=week_id)
        else:
            current_season = get_current_season()
            if current_season:
                qs = qs.filter(week__season=current_season)
        logger.debug(f"MatchUpInline queryset: {qs.query}")
        return qs


class WeekAdmin(admin.ModelAdmin):
    list_select_related = (
        "division",
        "season",
    )
    inlines = [
        MatchUpInline,
    ]
    list_display = ["__str__", "is_cancelled"]
    list_editable = ["is_cancelled"]
    list_display_links = ["__str__"]
    list_filter = ["division", "season", "is_cancelled"]

    actions = ["show_all_seasons"]

    def show_all_seasons(self, request, queryset):
        return queryset

    show_all_seasons.short_description = "Show All Seasons"

    def changelist_view(self, request, extra_context=None):
        if not request.GET.get("season__id__exact"):
            current_season = get_current_season()
            if current_season:
                query_string = urlencode({"season__id__exact": current_season.id})
                url = f"{request.path}?{query_string}"
                return redirect(url)
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        season_id = request.GET.get("season__id__exact")
        if season_id:
            qs = qs.filter(season_id=season_id)
        return qs

    def render_change_list(self, request, *args, **kwargs):
        extra_context = kwargs.get("extra_context", {})
        recent_seasons = Season.objects.order_by("-year", "-season_type")[:5]
        extra_context["recent_seasons"] = recent_seasons
        kwargs["extra_context"] = extra_context
        return super().render_change_list(request, *args, **kwargs)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "quick-cancel-week/<int:week_id>/",
                self.admin_site.admin_view(self.quick_cancel_week_view),
                name="leagues_week_quick_cancel",
            ),
            path(
                "quick-cancel-date/<str:date_str>/<int:cancelled>/",
                self.admin_site.admin_view(self.quick_cancel_date_view),
                name="leagues_week_quick_cancel_date",
            ),
            path(
                "quick-cancel-matchup/<int:matchup_id>/",
                self.admin_site.admin_view(self.quick_cancel_matchup_view),
                name="leagues_matchup_quick_cancel",
            ),
        ]
        return custom_urls + urls

    def has_quick_cancel_permission(self, request):
        return request.user.has_perm("leagues.can_quick_cancel_games")

    def quick_cancel_week_view(self, request, week_id):
        """Cancel or restore all games for a single Week, and stamp each MatchUp."""
        if not self.has_quick_cancel_permission(request):
            raise PermissionDenied
        if request.method != "POST":
            return redirect(reverse("admin:index"))
        week = Week.objects.select_related("division").get(pk=week_id)
        week.is_cancelled = not week.is_cancelled
        week.save()
        MatchUp.objects.filter(week=week).update(is_cancelled=week.is_cancelled)
        cache.delete("cancelled_games_ctx")
        status = "cancelled" if week.is_cancelled else "restored"
        messages.success(
            request,
            f"{week.division} on {week.date:%A, %B %-d} has been {status}.",
        )
        return redirect(reverse("admin:index"))

    def quick_cancel_date_view(self, request, date_str, cancelled):
        """Cancel or restore all games on a given date across all divisions."""
        if not self.has_quick_cancel_permission(request):
            raise PermissionDenied
        if request.method != "POST":
            return redirect(reverse("admin:index"))
        target_date = date.fromisoformat(date_str)
        updated = Week.objects.filter(date=target_date).update(
            is_cancelled=bool(cancelled)
        )
        MatchUp.objects.filter(week__date=target_date).update(
            is_cancelled=bool(cancelled)
        )
        cache.delete("cancelled_games_ctx")
        action = "cancelled" if cancelled else "restored"
        messages.success(
            request,
            f"All {updated} division(s) on {target_date:%A, %B %-d} have been {action}.",
        )
        return redirect(reverse("admin:index"))

    def quick_cancel_matchup_view(self, request, matchup_id):
        """Toggle is_cancelled on a single MatchUp. Syncs Week.is_cancelled."""
        if not self.has_quick_cancel_permission(request):
            raise PermissionDenied
        if request.method != "POST":
            return redirect(reverse("admin:index"))
        matchup = MatchUp.objects.select_related(
            "week__division", "hometeam", "awayteam"
        ).get(pk=matchup_id)
        matchup.is_cancelled = not matchup.is_cancelled
        matchup.save()
        # Keep Week.is_cancelled in sync: True only when every game is cancelled.
        week = matchup.week
        all_cancelled = not MatchUp.objects.filter(
            week=week, is_cancelled=False
        ).exists()
        week.is_cancelled = all_cancelled
        week.save()
        cache.delete("cancelled_games_ctx")
        status = "cancelled" if matchup.is_cancelled else "restored"
        messages.success(
            request,
            f"{matchup.awayteam} vs {matchup.hometeam} at "
            f"{matchup.time:%I:%M %p} has been {status}.",
        )
        return redirect(reverse("admin:index"))


class TeamAdmin(admin.ModelAdmin):
    inlines = [TeamStatInline, RosterInline]
    list_filter = ["is_active", "division", "season"]
    save_as = True
    raw_id_fields = ["division", "season"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("division", "season")


class SeasonAdmin(admin.ModelAdmin):
    list_filter = ("year",)


@admin.register(Ref)
class RefAdmin(admin.ModelAdmin):
    pass


@admin.register(HomePage)
class HomePageAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.wed_champ_photo:
            print(f"Uploaded file path: {obj.wed_champ_photo.name}")
            print(f"Storage backend: {obj.wed_champ_photo.storage}")


@admin.register(TeamPhoto)
class TeamPhotoAdmin(admin.ModelAdmin):
    pass


@admin.register(PlayerPhoto)
class PlayerPhotoAdmin(admin.ModelAdmin):
    pass


@admin.action(description="Approve selected photos and make them live")
def approve_pending_photos(modeladmin, request, queryset):
    approved = 0
    for pending in queryset.select_related("player"):
        old_live_photo = pending.player.player_photo
        live_photo = PlayerPhoto.objects.create(photo=pending.photo.name)
        pending.player.player_photo = live_photo
        pending.player.save()
        pending.delete()
        # Clean up the previous live photo (file + record) now that it's replaced.
        if old_live_photo:
            old_live_photo.photo.delete(save=False)
            old_live_photo.delete()
        approved += 1
    modeladmin.message_user(
        request,
        f"{approved} photo(s) approved and now live.",
        messages.SUCCESS,
    )


@admin.action(description="Reject selected photos and delete from storage")
def reject_pending_photos(modeladmin, request, queryset):
    rejected = 0
    for pending in queryset:
        pending.photo.delete(save=False)
        pending.delete()
        rejected += 1
    modeladmin.message_user(
        request,
        f"{rejected} photo(s) rejected and deleted.",
        messages.SUCCESS,
    )


@admin.register(PendingPlayerPhoto)
class PendingPlayerPhotoAdmin(admin.ModelAdmin):
    list_display = [
        "player",
        "photo_preview",
        "submitter_email",
        "submitted_at",
        "row_actions",
    ]
    list_filter = []
    readonly_fields = [
        "player",
        "submitted_at",
        "photo_preview_large",
        "submitter_email",
        "submitter_note",
    ]
    actions = [approve_pending_photos, reject_pending_photos]

    class Media:
        js = ("admin/js/pending_photo_modal.js",)

    # ------------------------------------------------------------------
    # Custom URLs: single-item approve / reject
    # ------------------------------------------------------------------

    def get_urls(self):
        custom = [
            path(
                "<int:pk>/approve/",
                self.admin_site.admin_view(self.approve_single_view),
                name="leagues_pendingplayerphoto_approve_single",
            ),
            path(
                "<int:pk>/reject/",
                self.admin_site.admin_view(self.reject_single_view),
                name="leagues_pendingplayerphoto_reject_single",
            ),
        ]
        return custom + super().get_urls()

    def approve_single_view(self, request, pk):
        pending = get_object_or_404(PendingPlayerPhoto, pk=pk)
        player = pending.player
        old_live_photo = player.player_photo
        live_photo = PlayerPhoto.objects.create(photo=pending.photo.name)
        player.player_photo = live_photo
        player.save()
        pending.delete()
        if old_live_photo:
            old_live_photo.photo.delete(save=False)
            old_live_photo.delete()
        self.message_user(
            request,
            f"Photo for {player} approved and now live.",
            messages.SUCCESS,
        )
        return redirect(reverse("admin:leagues_pendingplayerphoto_changelist"))

    def reject_single_view(self, request, pk):
        pending = get_object_or_404(PendingPlayerPhoto, pk=pk)
        player_name = str(pending.player)
        pending.photo.delete(save=False)
        pending.delete()
        self.message_user(
            request,
            f"Photo for {player_name} rejected and deleted.",
            messages.SUCCESS,
        )
        return redirect(reverse("admin:leagues_pendingplayerphoto_changelist"))

    # ------------------------------------------------------------------
    # List display columns
    # ------------------------------------------------------------------

    def photo_preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" data-photo-url="{}" '
                'style="height:48px;width:48px;object-fit:cover;border-radius:50%;'
                'cursor:zoom-in;" title="Click to enlarge">',
                obj.photo.url,
                obj.photo.url,
            )
        return "—"

    photo_preview.short_description = "Preview"

    def photo_preview_large(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" data-photo-url="{}" '
                'style="max-height:240px;max-width:240px;border-radius:4px;'
                'cursor:zoom-in;" title="Click to enlarge">',
                obj.photo.url,
                obj.photo.url,
            )
        return "—"

    photo_preview_large.short_description = "Photo"

    def row_actions(self, obj):
        approve_url = reverse(
            "admin:leagues_pendingplayerphoto_approve_single", args=[obj.pk]
        )
        reject_url = reverse(
            "admin:leagues_pendingplayerphoto_reject_single", args=[obj.pk]
        )
        return format_html(
            '<a href="{}" style="display:inline-block;padding:5px 12px;background:#2e7d32;'
            "color:#fff;border-radius:3px;font-size:12px;font-weight:600;"
            'text-decoration:none;margin-right:6px;">Approve</a>'
            '<a href="{}" style="display:inline-block;padding:5px 12px;background:#c62828;'
            "color:#fff;border-radius:3px;font-size:12px;font-weight:600;"
            'text-decoration:none;" '
            "onclick=\"return confirm('Permanently delete this photo?')\">Reject</a>",
            approve_url,
            reject_url,
        )

    row_actions.short_description = ""


admin.site.register(Player, PlayerAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Week, WeekAdmin)
admin.site.register(Season, SeasonAdmin)
admin.site.register(Division)
admin.site.register(Roster)
admin.site.register(Team_Stat)
admin.site.register(MatchUp, MatchUpAdmin)
admin.site.register(MatchUpGoalieStatus, MatchUpGoalieStatusAdmin)
admin.site.register(Stat)


# ===========================================================================
# Wednesday Draft League – Admin
# ===========================================================================


@admin.register(SeasonSignup)
class SeasonSignupAdmin(admin.ModelAdmin):
    list_display = (
        "last_name",
        "first_name",
        "email",
        "season",
        "primary_position",
        "secondary_position",
        "captain_interest_short",
        "is_returning",
        "linked_player",
        "submitted_at",
    )
    list_filter = ("season", "primary_position", "captain_interest", "is_returning")
    search_fields = ("first_name", "last_name", "email")
    autocomplete_fields = ("linked_player",)
    readonly_fields = ("submitted_at",)
    list_editable = ("is_returning", "linked_player")
    ordering = ("season", "last_name", "first_name")

    fieldsets = (
        (
            "Player Info",
            {
                "fields": ("season", "first_name", "last_name", "email"),
            },
        ),
        (
            "Positions",
            {
                "fields": ("primary_position", "secondary_position"),
            },
        ),
        (
            "Availability & Interest",
            {
                "fields": ("captain_interest", "notes"),
            },
        ),
        (
            "Commissioner",
            {
                "fields": ("is_returning", "linked_player", "submitted_at"),
                "description": "These fields are set by the commissioner, not the player.",
            },
        ),
    )

    def captain_interest_short(self, obj):
        labels = {
            SeasonSignup.CAPTAIN_YES: "Yes",
            SeasonSignup.CAPTAIN_OVERDUE: "Overdue",
            SeasonSignup.CAPTAIN_LAST_RESORT: "Last resort",
            SeasonSignup.CAPTAIN_NO: "No",
        }
        return labels.get(obj.captain_interest, "—")

    captain_interest_short.short_description = "Captain?"


class DraftRoundInline(admin.TabularInline):
    model = DraftRound
    extra = 0
    fields = ("round_number", "order_type")
    ordering = ("round_number",)


class DraftTeamInline(admin.TabularInline):
    model = DraftTeam
    extra = 0
    fields = (
        "captain",
        "team_name",
        "draft_position",
        "captain_draft_round",
        "captain_token_display",
    )
    readonly_fields = ("captain_token_display",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "captain":
            session_pk = request.resolver_match.kwargs.get("object_id")
            if session_pk:
                try:
                    session = DraftSession.objects.select_related("season").get(
                        pk=session_pk
                    )
                    kwargs["queryset"] = SeasonSignup.objects.filter(
                        season=session.season
                    ).order_by("last_name", "first_name")
                except DraftSession.DoesNotExist:
                    kwargs["queryset"] = SeasonSignup.objects.none()
            else:
                kwargs["queryset"] = SeasonSignup.objects.none()
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

    def captain_token_display(self, obj):
        if not obj.pk:
            return "—"
        return format_html(
            '<a href="/draft/{}/captain/{}/" target="_blank">Captain link</a>',
            obj.session_id,
            obj.captain_token,
        )

    captain_token_display.short_description = "Captain URL"


def _position_for_signup(signup):
    """Map SeasonSignup primary_position to Roster.POSITION_TYPE int."""
    mapping = {
        SeasonSignup.POSITION_CENTER: 1,
        SeasonSignup.POSITION_WING: 2,
        SeasonSignup.POSITION_DEFENSE: 3,
        SeasonSignup.POSITION_GOALIE: 4,
    }
    return mapping.get(signup.primary_position, 2)  # default Wing


def _secondary_position_for_signup(signup):
    """Map SeasonSignup secondary_position to Roster.POSITION_TYPE int (or None)."""
    if signup.secondary_position == SeasonSignup.POSITION_ONE_THING:
        return None
    mapping = {
        SeasonSignup.POSITION_CENTER: 1,
        SeasonSignup.POSITION_WING: 2,
        SeasonSignup.POSITION_DEFENSE: 3,
        SeasonSignup.POSITION_GOALIE: 4,
    }
    return mapping.get(signup.secondary_position)


@admin.register(DraftSession)
class DraftSessionAdmin(admin.ModelAdmin):
    actions = ["create_rosters_from_draft"]

    @admin.action(description="Create Django teams & rosters from completed draft")
    def create_rosters_from_draft(self, request, queryset):
        from django.db import transaction

        wed_division = Division.objects.filter(division=3).first()
        if not wed_division:
            self.message_user(
                request, "Wednesday Draft League division not found.", messages.ERROR
            )
            return

        created_teams = 0
        created_players = 0
        skipped = 0

        for session in queryset:
            if session.state != DraftSession.STATE_COMPLETE:
                self.message_user(
                    request,
                    f"Draft for {session.season} is not complete — skipped.",
                    messages.WARNING,
                )
                continue

            with transaction.atomic():
                for draft_team in session.teams.prefetch_related(
                    "draft_picks__signup"
                ).all():
                    # Create or find the Player record for the captain
                    captain_signup = draft_team.captain

                    # Create Team object
                    team, _ = Team.objects.get_or_create(
                        team_name=draft_team.team_name,
                        season=session.season,
                        defaults={
                            "division": wed_division,
                            "team_color": "",
                            "is_active": True,
                        },
                    )
                    created_teams += 1

                    for pick in draft_team.draft_picks.all():
                        signup = pick.signup

                        # Get or create the Player record
                        if signup.linked_player:
                            player = signup.linked_player
                        else:
                            player, p_created = Player.objects.get_or_create(
                                first_name__iexact=signup.first_name,
                                last_name__iexact=signup.last_name,
                                defaults={
                                    "first_name": signup.first_name,
                                    "last_name": signup.last_name,
                                    "email": signup.email,
                                    "is_active": True,
                                },
                            )
                            if p_created:
                                created_players += 1
                            # Update the signup to link this player
                            SeasonSignup.objects.filter(pk=signup.pk).update(
                                linked_player=player
                            )

                        pos1 = _position_for_signup(signup)
                        pos2 = _secondary_position_for_signup(signup)
                        is_captain = signup.pk == captain_signup.pk

                        roster_entry, r_created = Roster.objects.update_or_create(
                            player=player,
                            team=team,
                            defaults={
                                "position1": pos1,
                                "position2": pos2,
                                "is_captain": is_captain,
                                "is_substitute": False,
                                "is_primary_goalie": pos1 == 4,
                            },
                        )
                        if not r_created:
                            skipped += 1

        self.message_user(
            request,
            f"Done: {created_teams} team(s) created, {created_players} new player(s) created, {skipped} roster entries already existed.",
            messages.SUCCESS,
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "draft-setup/",
                self.admin_site.admin_view(self.draft_setup_hub),
                name="leagues_draftsession_draft_setup_hub",
            ),
        ]
        return custom + urls

    def draft_setup_hub(self, request):
        from django.template.response import TemplateResponse

        context = {
            **self.admin_site.each_context(request),
            "title": "Wednesday Draft Setup",
            "draft_sections": [
                {
                    "name": "Draft Sessions",
                    "description": (
                        "Create and configure draft sessions, "
                        "rounds, and team captains."
                    ),
                    "changelist_url": reverse("admin:leagues_draftsession_changelist"),
                    "add_url": reverse("admin:leagues_draftsession_add"),
                    "count": DraftSession.objects.count(),
                },
                {
                    "name": "Season Signups",
                    "description": "View and manage player signups for the draft.",
                    "changelist_url": reverse("admin:leagues_seasonsignup_changelist"),
                    "add_url": reverse("admin:leagues_seasonsignup_add"),
                    "count": SeasonSignup.objects.count(),
                },
                {
                    "name": "Draft Picks",
                    "description": (
                        "View completed picks, manage trades, "
                        "and correct draft errors."
                    ),
                    "changelist_url": reverse("admin:leagues_draftpick_changelist"),
                    "add_url": None,
                    "count": DraftPick.objects.count(),
                },
            ],
        }
        return TemplateResponse(request, "admin/leagues/draft_setup.html", context)

    list_display = (
        "season",
        "state",
        "num_teams",
        "num_rounds",
        "signups_open",
        "signup_count",
        "board_links",
    )
    list_filter = ("state", "signups_open")
    readonly_fields = (
        "commissioner_token",
        "created_at",
        "commissioner_url",
        "spectator_url",
        "signup_url",
        "captain_portal_url",
    )
    inlines = [DraftRoundInline, DraftTeamInline]

    fieldsets = (
        (
            "Season & State",
            {
                "fields": ("season", "state", "signups_open"),
            },
        ),
        (
            "Draft Configuration",
            {
                "fields": ("num_teams", "num_rounds"),
                "description": (
                    "Set these before starting the draft. "
                    "Rounds are configured in the Rounds section below."
                ),
            },
        ),
        (
            "URLs",
            {
                "fields": (
                    "signup_url",
                    "captain_portal_url",
                    "spectator_url",
                    "commissioner_url",
                ),
                "description": "Share these links with participants.",
                "classes": ("collapse",),
            },
        ),
        (
            "System",
            {
                "fields": ("commissioner_token", "created_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def signup_count(self, obj):
        return obj.season.signups.count()

    signup_count.short_description = "Signups"

    def commissioner_url(self, obj):
        if not obj.pk:
            return "—"
        url = f"/draft/{obj.pk}/commissioner/{obj.commissioner_token}/"
        return format_html('<a href="{}" target="_blank">{}</a>', url, url)

    commissioner_url.short_description = "Commissioner URL"

    def spectator_url(self, obj):
        if not obj.pk:
            return "—"
        url = f"/draft/{obj.pk}/"
        return format_html('<a href="{}" target="_blank">{}</a>', url, url)

    spectator_url.short_description = "Spectator URL"

    def signup_url(self, obj):
        if not obj.pk:
            return "—"
        url = f"/draft/signup/{obj.season_id}/"
        return format_html('<a href="{}" target="_blank">{}</a>', url, url)

    signup_url.short_description = "Signup Form URL"

    def captain_portal_url(self, obj):
        if not obj.pk:
            return "—"
        url = f"/draft/{obj.pk}/captains/"
        return format_html('<a href="{}" target="_blank">{}</a>', url, url)

    captain_portal_url.short_description = (
        "Captain Portal URL (share with all captains)"
    )

    def board_links(self, obj):
        if not obj.pk:
            return "—"
        return format_html(
            '<a href="/draft/{}/" target="_blank">Board</a> | '
            '<a href="/draft/{}/commissioner/{}/" target="_blank">Commissioner</a> | '
            '<a href="/draft/{}/captains/" target="_blank">Captains</a>',
            obj.pk,
            obj.pk,
            obj.commissioner_token,
            obj.pk,
        )

    board_links.short_description = "Links"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Auto-create DraftRound entries when num_rounds is set/changed
        if obj.num_rounds > 0:
            existing_rounds = set(obj.rounds.values_list("round_number", flat=True))
            for r in range(1, obj.num_rounds + 1):
                if r not in existing_rounds:
                    DraftRound.objects.create(
                        session=obj,
                        round_number=r,
                        order_type=DraftRound.ORDER_SNAKE,
                    )
            # Remove rounds beyond num_rounds if reduced
            obj.rounds.filter(round_number__gt=obj.num_rounds).delete()


@admin.register(DraftPick)
class DraftPickAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "round_number",
        "pick_number",
        "team",
        "signup",
        "is_auto_captain",
        "traded",
        "trade_note",
        "picked_at",
    )
    list_filter = ("session", "round_number", "is_auto_captain", "traded")
    search_fields = ("signup__first_name", "signup__last_name", "team__team_name")
    ordering = ("session", "round_number", "pick_number")
    readonly_fields = ("picked_at",)
    list_editable = ("team", "traded", "trade_note")
    actions = ["swap_picks"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("session", "team__captain", "signup")
        )

    @admin.action(description="Swap players between two selected picks")
    def swap_picks(self, request, queryset):
        picks = list(queryset)
        if len(picks) != 2:
            self.message_user(
                request, "Select exactly 2 picks to swap.", messages.WARNING
            )
            return

        pick_a, pick_b = picks
        if pick_a.session_id != pick_b.session_id:
            self.message_user(
                request,
                "Both picks must be from the same draft session.",
                messages.ERROR,
            )
            return

        # Swap teams
        team_a, team_b = pick_a.team, pick_b.team
        note = f"Traded with {pick_b.signup.full_name} ({team_b.team_name})"
        note_b = f"Traded with {pick_a.signup.full_name} ({team_a.team_name})"

        pick_a.team = team_b
        pick_a.traded = True
        pick_a.trade_note = note
        pick_a.save()

        pick_b.team = team_a
        pick_b.traded = True
        pick_b.trade_note = note_b
        pick_b.save()

        self.message_user(
            request,
            f"Swapped: {pick_a.signup.full_name} → {team_b.team_name} and "
            f"{pick_b.signup.full_name} → {team_a.team_name}.",
            messages.SUCCESS,
        )


# Swap the admin site class so get_app_list reorganizes the index page.
# All existing admin.site.register() / @admin.register() calls remain valid —
# we're changing the class of the existing singleton, not creating a new one.
admin.site.__class__ = _DCHockeyAdminSite
