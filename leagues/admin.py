# leagues/admin.py
from django import forms
from django.contrib import admin
from django.db import models
from django.db.models import Q, Max
from django.utils.http import urlencode
from django.urls import reverse
from django.shortcuts import redirect

from dal import autocomplete
from .forms import MatchUpForm
from .fields import TwelveHourTimeField
from .widgets import Time12HourWidget
from leagues.models import Division, Player, Team, Roster, Team_Stat, Week, MatchUp, Stat, Ref, Season, HomePage, TeamPhoto, PlayerPhoto

from .filters import MatchupDateFilter, RecentSeasonsFilter, CurrentSeasonWeekFilter

def get_current_season():
    try:
        current_season_instance = Season.objects.filter(is_current_season=True).first()
        return current_season_instance
    except Season.DoesNotExist:
        return None

def get_current_season_for_division(division_id):
    try:
        max_year = Season.objects.filter(
            team__division_id=division_id
        ).aggregate(max_year=Max('year'))['max_year']

        max_season_type = Season.objects.filter(
            team__division_id=division_id,
            year=max_year
        ).aggregate(max_season_type=Max('season_type'))['max_season_type']

        current_season_instance = Season.objects.get(
            year=max_year,
            season_type=max_season_type
        )
        return current_season_instance
    except Season.DoesNotExist:
        return None

class RosterInlineForm(forms.ModelForm):
    class Meta:
        model = Roster
        fields = '__all__'
        widgets = {
            'player': autocomplete.ModelSelect2(url='leagues:player-autocomplete')
        }

class RosterInline(admin.TabularInline):
    model = Roster
    form = RosterInlineForm
    extra = 1

class TeamStatInline(admin.TabularInline):
    model = Team_Stat
    extra = 1

class PlayerAdmin(admin.ModelAdmin):
    search_fields = ['last_name', 'first_name']
    list_select_related = ('player_photo',)

class StatInline(admin.TabularInline):
    model = Stat
    extra = 1

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        match_id = request.resolver_match.kwargs.get('object_id')
        if match_id:
            qs = qs.filter(matchup_id=match_id)
        return qs

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        match_id = request.resolver_match.kwargs.get('object_id')
        if db_field.name in ["player", "team"] and match_id:
            try:
                match = MatchUp.objects.select_related('hometeam', 'awayteam', 'week__season').get(id=match_id)
                if db_field.name == "player":
                    kwargs['queryset'] = Player.objects.filter(
                        (Q(roster__team__in=[match.hometeam, match.awayteam]) &
                         Q(roster__team__season=match.week.season)) |
                        Q(roster__position1=4) | Q(roster__position2=4)
                    ).distinct()
                elif db_field.name == "team":
                    kwargs['queryset'] = Team.objects.filter(
                        id__in=[match.hometeam.id, match.awayteam.id],
                        season=match.week.season
                    )
            except MatchUp.DoesNotExist:
                print("Could not find the matchup to filter players or teams.")
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

class MatchUpAdmin(admin.ModelAdmin):
    form = MatchUpForm
    list_select_related = ('hometeam', 'awayteam', 'week',)
    inlines = [StatInline,]
    list_filter = ('week__division', 'week__season')
    raw_id_fields = ['hometeam', 'awayteam']
    list_display = ['week', 'formatted_time', 'awayteam', 'hometeam']

    formfield_overrides = {
        models.TimeField: {'form_class': TwelveHourTimeField, 'widget': Time12HourWidget},
    }

    def formatted_time(self, obj):
        if obj.time:
            try:
                return obj.time.strftime('%I:%M %p')
            except ValueError:
                return obj.time
        return None

    formatted_time.short_description = 'Time'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        division_id = request.GET.get('week__division__exact')
        season_id = request.GET.get('week__season__exact')

        if division_id:
            current_season_instance = get_current_season_for_division(division_id)
            if current_season_instance:
                qs = qs.filter(week__season=current_season_instance)
        elif season_id:
            qs = qs.filter(week__season_id=season_id)
        else:
            current_season = get_current_season()
            if current_season:
                qs = qs.filter(week__season=current_season)

        return qs

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name in ["hometeam", "awayteam"]:
            kwargs['queryset'] = Team.objects.filter(is_active=True).select_related('division')
        elif db_field.name == "week":
            matchup_id = request.resolver_match.kwargs.get('object_id')
            if matchup_id:
                try:
                    matchup = MatchUp.objects.select_related('week__season').get(id=matchup_id)
                    kwargs['queryset'] = Week.objects.filter(
                        division=matchup.hometeam.division,
                        season=matchup.week.season
                    )
                except MatchUp.DoesNotExist:
                    print("Could not find the matchup to filter weeks.")
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

    def render_change_list(self, request, *args, **kwargs):
        extra_context = kwargs.get('extra_context', {})
        recent_seasons = Season.objects.order_by('-year', '-season_type')[:5]
        extra_context['recent_seasons'] = recent_seasons
        kwargs['extra_context'] = extra_context
        return super().render_change_list(request, *args, **kwargs)

class MatchUpInline(admin.TabularInline):
    model = MatchUp
    form = MatchUpForm
    extra = 4
    raw_id_fields = ['awayteam', 'hometeam']

    formfield_overrides = {
        models.TimeField: {'form_class': TwelveHourTimeField, 'widget': Time12HourWidget},
    }

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        current_season = get_current_season()
        if current_season:
            qs = qs.filter(week__season=current_season)
        return qs

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name in ["awayteam", "hometeam"]:
            kwargs['queryset'] = Team.objects.filter(is_active=True).select_related('division')
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

class WeekAdmin(admin.ModelAdmin):
    list_select_related = ('division', 'season',)
    inlines = [MatchUpInline,]
    list_filter = ['season', 'division']

    actions = ['show_all_seasons']

    def show_all_seasons(self, request, queryset):
        return queryset
    show_all_seasons.short_description = "Show All Seasons"

    def changelist_view(self, request, extra_context=None):
        if not request.GET.get('season__id__exact'):
            current_season = get_current_season()
            if current_season:
                query_string = urlencode({'season__id__exact': current_season.id})
                url = f"{request.path}?{query_string}"
                return redirect(url)
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        season_id = request.GET.get('season__id__exact')
        if season_id:
            qs = qs.filter(season_id=season_id)
        else:
            current_season = get_current_season()
            if current_season:
                qs = qs.filter(season=current_season)
        return qs

    def render_change_list(self, request, *args, **kwargs):
        extra_context = kwargs.get('extra_context', {})
        recent_seasons = Season.objects.order_by('-year', '-season_type')[:5]
        extra_context['recent_seasons'] = recent_seasons
        kwargs['extra_context'] = extra_context
        return super().render_change_list(request, *args, **kwargs)

class TeamAdmin(admin.ModelAdmin):
    inlines = [TeamStatInline, RosterInline]
    list_filter = ['is_active', 'division', 'season']
    save_as = True
    raw_id_fields = ['division', 'season']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('division', 'season')

class SeasonAdmin(admin.ModelAdmin):
    list_filter = ('year',)

@admin.register(Ref)
class RefAdmin(admin.ModelAdmin):
    pass

@admin.register(HomePage)
class HomePageAdmin(admin.ModelAdmin):
    pass

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
