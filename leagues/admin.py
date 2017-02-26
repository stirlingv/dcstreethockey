from django.contrib import admin

from reversion.admin import VersionAdmin

from leagues.models import Player, Team, Roster, Season, League, Games, Stats, Refs

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    pass

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    pass

@admin.register(Roster)
class RosterAdmin(admin.ModelAdmin):
    pass

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    pass

@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    pass

@admin.register(Games)
class GamesAdmin(admin.ModelAdmin):
    pass

@admin.register(Stats)
class StatsAdmin(admin.ModelAdmin):
    pass

@admin.register(Refs)
class RefaAdmin(admin.ModelAdmin):
    pass