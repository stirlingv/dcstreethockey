from django import template
 
register = template.Library()

@register.filter
def division_type(division):
    if division == 1: return "D1"
    if division == 2: return "D2"
    if division == 3: return "Draft"
    if division == 4: return "Monday Coed"

    return division

@register.filter
def season_type(season):
    if season == 1: return "Spring"
    if season == 2: return "Summer"
    if season == 3: return "Fall"
    if season == 4: return "Winter"

    return season