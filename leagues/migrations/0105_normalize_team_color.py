from django.db import migrations

# Maps any known legacy team_color value (case/whitespace variations, plus
# ad-hoc values like "Gold" and the "#8b1a1a" placeholder hex the draft
# finalize flow used to write) onto the canonical jersey color names.
CANONICAL_COLORS = {
    "black": "Black",
    "blue": "Blue",
    "green": "Green",
    "grey": "Grey",
    "gray": "Grey",
    "maroon": "Maroon",
    "orange": "Orange",
    "pink": "Pink",
    "purple": "Purple",
    "red": "Red",
    "teal": "Teal",
    "white": "White",
    "yellow": "Yellow",
    "gold": "Yellow",
    "#8b1a1a": "Maroon",
}


def normalize_team_colors(apps, schema_editor):
    Team = apps.get_model("leagues", "Team")
    for team in Team.objects.all():
        key = team.team_color.strip().lower()
        canonical = CANONICAL_COLORS.get(key)
        if canonical and canonical != team.team_color:
            team.team_color = canonical
            team.save(update_fields=["team_color"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0104_alter_team_color_choices"),
    ]

    operations = [
        migrations.RunPython(normalize_team_colors, noop_reverse),
    ]
