from django import template
from django.templatetags.static import static
from leagues.models import Division

register = template.Library()


@register.filter
def division_type(division):
    if division == 1:
        return "D1"
    if division == 2:
        return "D2"
    if division == 3:
        return "Draft"
    if division == 4:
        return "Mon A"
    if division == 5:
        return "Mon B"

    return division


@register.filter
def season_type(season):
    if season == 1:
        return "Spring"
    if season == 2:
        return "Summer"
    if season == 3:
        return "Fall"
    if season == 4:
        return "Winter"

    return season


@register.filter
def get_division_name(value):
    try:
        value = int(value)
    except (ValueError, TypeError):
        return "Unknown"

    for division in Division.DIVISION_TYPE:
        if division[0] == value:
            return division[1]
    return "Unknown"


@register.filter
def get_item(dictionary, key):
    print(f"get_item called with dictionary: {dictionary}, key: {key}")
    try:
        return dictionary.get(key)
    except AttributeError:
        return None


@register.filter
def simplify_division_name(division):
    """Simplify division names for display."""
    # If division is a model instance, get its name field
    if hasattr(division, "name"):
        division_name = division.name
    else:
        division_name = str(division)  # Convert to string if it's not a model instance

    # Simplify the division name
    if "Wednesday" in division_name:
        return "Wednesday"
    if "Sunday" in division_name:
        return "Sunday"
    if "Monday" in division_name:
        return "Monday"
    return division_name


@register.filter
def weather_emoji(description):
    """Return an emoji based on the weather description."""
    if "clear" in description.lower():
        return "☀️"  # Sun emoji
    if "cloud" in description.lower():
        return "☁️"  # Cloud emoji
    if "rain" in description.lower():
        return "🌧️"  # Rain emoji
    if "snow" in description.lower():
        return "❄️"  # Snow emoji
    if "storm" in description.lower():
        return "⛈️"  # Storm emoji
    if "mist" in description.lower() or "fog" in description.lower():
        return "🌫️"  # Fog emoji
    return "🌈"  # Default emoji (rainbow)


@register.simple_tag
def jersey_path():
    """Returns the static path for jersey images."""
    return static("img/emojis/")
