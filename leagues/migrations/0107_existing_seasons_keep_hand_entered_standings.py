"""
Standings are now computed from game results for every season created from
here on. Every season that already exists was kept by hand, so mark those as
hand-entered so their records are left exactly as they are.

Also clears the ``is_current_season`` flag: the site now works out the
current season from the schedule (leagues/seasons.py), and sixteen stale
flags were still set.
"""

from django.db import migrations


def mark_existing_seasons(apps, schema_editor):
    Season = apps.get_model("leagues", "Season")
    Season.objects.update(standings_from_games=False, is_current_season=None)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0106_matchup_went_to_overtime_season_standings_from_games"),
    ]

    operations = [
        migrations.RunPython(mark_existing_seasons, noop),
    ]
