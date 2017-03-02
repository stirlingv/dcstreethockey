from django.contrib import admin

from reversion.admin import VersionAdmin

from leagues.models import Player, Team, Roster, Division, Season, Team_Stat, Game, MatchUp, Stat, Ref

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    pass

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    pass

@admin.register(Roster)
class RosterAdmin(admin.ModelAdmin):
    pass

@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    pass

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    pass

@admin.register(Team_Stat)
class Team_StatAdmin(admin.ModelAdmin):
    pass

@admin.register(MatchUp)
class MatchUpAdmin(admin.ModelAdmin):
    pass

@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    pass

@admin.register(Stat)
class StatAdmin(admin.ModelAdmin):
    pass

@admin.register(Ref)
class RefAdmin(admin.ModelAdmin):
    pass