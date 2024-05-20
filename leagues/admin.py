from django.contrib import admin
from django.db.models import Q
from leagues.models import Division, Player, Team, Roster, Team_Stat, Week, MatchUp, Stat, Ref, Season, HomePage, TeamPhoto, PlayerPhoto
from django.contrib.admin import SimpleListFilter
from .filters import MatchupDateFilter, RecentSeasonsFilter, CurrentSeasonWeekFilter

def get_current_season():
    return Season.objects.filter(is_current_season=True).first()

class CurrentSeasonFilter(SimpleListFilter):
    title = 'current season'
    parameter_name = 'current_season'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Current Season'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            current_season = get_current_season()
            if current_season:
                return queryset.filter(week__season=current_season)
        return queryset

class RosterInline(admin.TabularInline):
    model = Roster
    extra = 1
    raw_id_fields = ['player']

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
                        Q(roster__team__in=[match.hometeam, match.awayteam]) &
                        Q(roster__team__season=match.week.season) |
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
    list_select_related = (
        'hometeam',
        'awayteam',
        'week',
    )
    inlines = [
        StatInline,
    ]
    list_filter = (
        ('week__division', admin.RelatedOnlyFieldListFilter),
        RecentSeasonsFilter,
        MatchupDateFilter,
        CurrentSeasonFilter,
    )
    raw_id_fields = ['hometeam', 'awayteam']

    actions = ['show_all_seasons']

    def show_all_seasons(self, request, queryset):
        return queryset

    show_all_seasons.short_description = "Show All Seasons"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related('hometeam', 'awayteam', 'week__season')

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name in ["hometeam", "awayteam"]:
            kwargs['queryset'] = Team.objects.filter(is_active=True).select_related('division')
        elif db_field.name == "week":
            # Filter weeks by division and season of the matchup
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

class MatchUpInline(admin.TabularInline):
    model = MatchUp
    extra = 4
    raw_id_fields = ['awayteam', 'hometeam']

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name in ["awayteam", "hometeam"]:
            kwargs['queryset'] = Team.objects.filter(is_active=True).select_related('division')
        return super().formfield_for_foreignkey(db_field, request=request, **kwargs)

class WeekAdmin(admin.ModelAdmin):
    list_select_related = (
        'division',
        'season',
    )
    inlines = [
        MatchUpInline,
    ]
    list_filter = ['season', 'division', CurrentSeasonFilter]

    actions = ['show_all_seasons']

    def show_all_seasons(self, request, queryset):
        return queryset

    show_all_seasons.short_description = "Show All Seasons"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        current_season = get_current_season()
        if current_season:
            # Filter the queryset to include only the weeks for the current season
            qs = qs.filter(season=current_season)
            # Get the matchup ID from the request URL
            matchup_id = request.resolver_match.kwargs.get('object_id')
            if matchup_id:
                # Get the division IDs of the awayteam and hometeam in the selected matchup
                division_ids = MatchUp.objects.filter(id=matchup_id).values_list('awayteam__division', 'hometeam__division')
                # Filter the queryset to include only the weeks with divisions matching those of the teams in the matchup
                qs = qs.filter(division__in=division_ids)
        return qs

class TeamAdmin(admin.ModelAdmin):
    inlines = [TeamStatInline, RosterInline,]
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
admin.site.register(MatchUp, MatchUpAdmin)
admin.site.register(Week, WeekAdmin)
admin.site.register(Season, SeasonAdmin)
