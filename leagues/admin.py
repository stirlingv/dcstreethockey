from django.contrib import admin
from django.db.models import Q

from leagues.models import Player, Team, Roster, Team_Stat, Week, MatchUp, Stat, Ref, Season

class RosterInline(admin.TabularInline):
    model = Roster

class TeamStatInline(admin.TabularInline):
    model = Team_Stat
    extra = 1

class TeamAdmin(admin.ModelAdmin):
    inlines = [
            TeamStatInline,
            RosterInline,
            ]
    list_filter = ['is_active','season','division']
    save_as = True

class PlayerAdmin(admin.ModelAdmin):
    inlines = [RosterInline]
    search_fields = ['last_name', 'first_name']

class StatInline(admin.TabularInline):
    model = Stat
    extra = 1

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        try:
            match_id = str(request.path.strip('/').split('/')[-2])
            if db_field.name == "player":
                match = MatchUp.objects.filter(id=match_id).last()
                kwargs['queryset'] = Player.objects.filter(((
                        Q(roster__team=match.hometeam) | Q(
                        roster__team=match.awayteam)) & Q(
                        roster__team__season=match.week.season))  | Q(
                        roster__position1=4) | Q(roster__position2=4)).order_by(
                        'last_name','first_name').distinct(
                        'last_name', 'first_name')
            elif db_field.name == "team":
                match = MatchUp.objects.filter(id=match_id).last()
                kwargs['queryset'] = Team.objects.filter(
                        Q(id=match.hometeam.id) | Q(
                        id=match.awayteam.id)).filter(
                        Q(season=match.week.season))
        except Exception as e:
           print "Could not filter players or teams for admin view of matchup." + str(e)
        return super(StatInline, self).formfield_for_foreignkey(db_field, request=None, **kwargs)


class MatchUpAdmin(admin.ModelAdmin):
    inlines = [
            StatInline,
            ]
    list_filter = ['week__season', 'week']

class MatchUpInline(admin.TabularInline):
    model = MatchUp
    extra = 4

class WeekAdmin(admin.ModelAdmin):
    inlines = [
            MatchUpInline,
            ]
    list_filter = ['season', 'division']

@admin.register(Ref)
class RefAdmin(admin.ModelAdmin):
    pass

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_filter = ['year']

admin.site.register(Player, PlayerAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(MatchUp, MatchUpAdmin)
admin.site.register(Week, WeekAdmin)
