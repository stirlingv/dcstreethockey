from django import template
from leagues.models import Division

register = template.Library()

@register.filter
def division_type(division):
    if division == 1: return "D1"
    if division == 2: return "D2"
    if division == 3: return "Draft"
    if division == 4: return "Mon A"
    if division == 5: return "Mon B"

    return division

@register.filter
def season_type(season):
    if season == 1: return "Spring"
    if season == 2: return "Summer"
    if season == 3: return "Fall"
    if season == 4: return "Winter"

    return season

@register.filter
def get_division_name(value):
    try:
        value = int(value)
    except (ValueError, TypeError):
        return 'Unknown'
    
    for division in Division.DIVISION_TYPE:
        if division[0] == value:
            return division[1]
    return 'Unknown'