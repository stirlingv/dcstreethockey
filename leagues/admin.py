from django.contrib import admin
from django.db.models import Q

from leagues.models import Player, Team, Roster, Team_Stat, Week, MatchUp, Stat, Ref

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

class PlayerAdmin(admin.ModelAdmin):
    inlines = [RosterInline]

class StatInline(admin.TabularInline):
    model = Stat
    extra = 1

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
	try:
	    match_id = str(request.path.strip('/').split('/')[-2])
            if db_field.name == "player":
                match = MatchUp.objects.filter(id=match_id).last()
                kwargs['queryset'] = Player.objects.filter(
                        Q(roster__team__team_name=match.hometeam.team_name) | Q(
                        roster__team__team_name=match.awayteam.team_name) | Q(
                        roster__position1=4) | Q(roster__position2=4))
            elif db_field.name == "team":
                match = MatchUp.objects.filter(id=match_id).last()
                kwargs['queryset'] = Team.objects.filter(
                        Q(team_name=match.hometeam.team_name) | Q(
                        team_name=match.awayteam.team_name))
        except:
           print "Could not filter players or teams for admin view of matchup."
        return super(StatInline, self).formfield_for_foreignkey(db_field, request=None, **kwargs)


class MatchUpAdmin(admin.ModelAdmin):
    inlines = [
            StatInline,
            ]

class MatchUpInline(admin.TabularInline):
    model = MatchUp
    extra = 4

class WeekAdmin(admin.ModelAdmin):
    inlines = [
            MatchUpInline,
            ]

@admin.register(Ref)
class RefAdmin(admin.ModelAdmin):
    pass

admin.site.register(Player, PlayerAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(MatchUp, MatchUpAdmin)
admin.site.register(Week, WeekAdmin)
