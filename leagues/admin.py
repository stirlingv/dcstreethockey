from django.contrib import admin

from reversion.admin import VersionAdmin

from leagues.models import Player, Team, Roster, Division, Season, Team_Stat, Week, MatchUp, Stat, Ref

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    pass

# @admin.register(Team, Season)

# class SeasonInline(admin.TabularInline):
#         model = Season
# class TeamAdmin(admin.ModelAdmin):
#     actions = ['start_new_season']
#     inlines = [
#         SeasonInLine,
#     ]
#     start_new_season.short_description = "Start new season"

#     pass    
def start_new_season(modeladmin, request, queryset):
    for obj in queryset:
        do_something_with(obj)
start_new_season.short_description = "Register selected teams for a new season"

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    actions = ['start_new_season']
# admin.site.register(Team, TeamAdmin)
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

@admin.register(Week)
class WeekAdmin(admin.ModelAdmin):
    pass

@admin.register(Stat)
class StatAdmin(admin.ModelAdmin):
    pass

@admin.register(Ref)
class RefAdmin(admin.ModelAdmin):
    pass




# class RosterInline(admin.TabularInline):
#     model = Roster

# class TeamInline(admin.TabularInline):
#     model = Team


# class MatchUpAdmin(admin.ModelAdmin):
#      inlines = [TeamInline]

# admin.site.register(MatchUp, MatchUpAdmin)

    
