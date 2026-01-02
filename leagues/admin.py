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
from django.shortcuts import redirect, render
from django.http import HttpResponseRedirect

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
    Stat,
    Ref,
    Season,
    HomePage,
    TeamPhoto,
    PlayerPhoto,
)
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)


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
            ("recent", "Last 30 days"),
        )

    def queryset(self, request, queryset):
        today = timezone.localdate()
        if self.value() == "all":
            return queryset
        if self.value() == "upcoming":
            return queryset.filter(week__date__gte=today)
        if self.value() == "recent":
            return queryset.filter(week__date__gte=today - timedelta(days=30))
        return queryset


def _get_team_roster_goalie(team):
    """
    Get the primary goalie for a team.
    Priority: is_primary_goalie=True > first non-substitute goalie
    """
    if not team:
        return None

    from django.db.models import Q

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


def _apply_default_matchup_filters(request):
    if request.GET.get("timeframe") or request.GET.get("season_ids"):
        return None
    current_seasons = Season.objects.filter(is_current_season=True)
    if not current_seasons.exists():
        return None
    query = request.GET.copy()
    query["timeframe"] = "upcoming"
    query["season_ids"] = ",".join(
        str(season_id) for season_id in current_seasons.values_list("id", flat=True)
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
    form = MatchUpForm
    list_select_related = (
        "hometeam",
        "awayteam",
        "week",
        "away_goalie",
        "home_goalie",
    )
    inlines = [
        StatInline,
    ]
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
        (
            "Away Team Goalie",
            {
                "fields": ("away_goalie", "away_goalie_status"),
                "classes": ("collapse",),
            },
        ),
        (
            "Home Team Goalie",
            {
                "fields": ("home_goalie", "home_goalie_status"),
                "classes": ("collapse",),
            },
        ),
    )

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

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name in ["hometeam", "awayteam"]:
            kwargs["queryset"] = Team.objects.filter(is_active=True).select_related(
                "division"
            )
        elif db_field.name in ["away_goalie", "home_goalie"]:
            # Include all active goalies, plus any goalie who played in the last 2 years
            # (even if inactive) so admins can assign returning subs
            from datetime import date

            current_year = date.today().year
            recent_years = [current_year, current_year - 1, current_year - 2]

            # Active goalies OR recently played goalies (even if inactive)
            kwargs["queryset"] = (
                Player.objects.filter(
                    Q(roster__position1=4) | Q(roster__position2=4),
                )
                .filter(
                    Q(is_active=True) | Q(roster__team__season__year__in=recent_years)
                )
                .distinct()
                .order_by("last_name", "first_name")
            )
        elif db_field.name == "week":
            matchup_id = request.resolver_match.kwargs.get("object_id")
            if matchup_id:
                try:
                    matchup = MatchUp.objects.select_related("week__season").get(
                        id=matchup_id
                    )
                    kwargs["queryset"] = Week.objects.filter(
                        division=matchup.hometeam.division, season=matchup.week.season
                    )
                except MatchUp.DoesNotExist:
                    print("Could not find the matchup to filter weeks.")
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

    def render_change_list(self, request, *args, **kwargs):
        extra_context = kwargs.get("extra_context", {})
        recent_seasons = Season.objects.order_by("-year", "-season_type")[:5]
        extra_context["recent_seasons"] = recent_seasons
        kwargs["extra_context"] = extra_context
        return super().render_change_list(request, *args, **kwargs)

    def get_changelist_form(self, request, **kwargs):
        class MatchUpGoalieForm(forms.ModelForm):
            class Meta:
                model = MatchUp
                fields = list(self.list_editable)

        return MatchUpGoalieForm

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
                if instance.awayteam_id:
                    away_roster_goalie = _get_team_roster_goalie(instance.awayteam)
                    form.fields["away_goalie"].widget.attrs["data-roster-goalie-id"] = (
                        str(away_roster_goalie.pk) if away_roster_goalie else ""
                    )
                if instance.hometeam_id:
                    home_roster_goalie = _get_team_roster_goalie(instance.hometeam)
                    form.fields["home_goalie"].widget.attrs["data-roster-goalie-id"] = (
                        str(home_roster_goalie.pk) if home_roster_goalie else ""
                    )
                if (
                    instance.away_goalie_id is None
                    and instance.away_goalie_status == 3
                    and instance.awayteam_id
                    and not form.initial.get("away_goalie")
                ):
                    if away_roster_goalie:
                        form.initial["away_goalie"] = away_roster_goalie.pk
                        form.fields["away_goalie"].initial = away_roster_goalie.pk
                if (
                    instance.home_goalie_id is None
                    and instance.home_goalie_status == 3
                    and instance.hometeam_id
                    and not form.initial.get("home_goalie")
                ):
                    if home_roster_goalie:
                        form.initial["home_goalie"] = home_roster_goalie.pk
                        form.fields["home_goalie"].initial = home_roster_goalie.pk
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
                name="leagues_matchup_add_goalie_sub",
            ),
        ]
        return custom_urls + urls

    def add_goalie_sub_view(self, request):
        """Custom view to add a new goalie sub (Player + Roster entry)."""
        from .models import Season, Team

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
            phone = forms.CharField(max_length=20, required=False)

        if request.method == "POST":
            form = AddGoalieSubForm(request.POST)
            if form.is_valid():
                # Create the player
                player = Player.objects.create(
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    email=form.cleaned_data["email"] or None,
                    phone=form.cleaned_data["phone"] or None,
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
                # Redirect back to matchup list with preserved filters
                redirect_url = reverse("admin:leagues_matchup_changelist")
                if request.GET.get("_popup"):
                    return render(
                        request,
                        "admin/leagues/matchup/add_goalie_sub_done.html",
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
        return render(request, "admin/leagues/matchup/add_goalie_sub.html", context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["add_goalie_sub_url"] = reverse(
            "admin:leagues_matchup_add_goalie_sub"
        )
        redirect_url = _apply_default_matchup_filters(request)
        if redirect_url:
            return redirect(redirect_url)
        return super().changelist_view(request, extra_context=extra_context)

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
    list_filter = ["division", "season"]

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


admin.site.register(Player, PlayerAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Week, WeekAdmin)
admin.site.register(Season, SeasonAdmin)
admin.site.register(Division)
admin.site.register(Roster)
admin.site.register(Team_Stat)
admin.site.register(MatchUp, MatchUpAdmin)
admin.site.register(Stat)
