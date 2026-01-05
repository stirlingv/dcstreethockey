from __future__ import annotations

from django.core.management.base import BaseCommand

from leagues.models import Team, Season


class Command(BaseCommand):
    help = "List captain goalie update URLs for all active teams in current seasons"

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            type=str,
            default="https://dcstreethockey.com",
            help="Base URL for the site (default: https://dcstreethockey.com)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Show all active teams, not just current season teams",
        )

    def handle(self, *args, **options):
        base_url = options["base_url"].rstrip("/")
        show_all = options["all"]

        if show_all:
            teams = Team.objects.filter(is_active=True).select_related(
                "season", "division"
            )
            self.stdout.write("All Active Teams:\n")
        else:
            current_seasons = Season.objects.filter(is_current_season=True)
            teams = Team.objects.filter(
                is_active=True, season__in=current_seasons
            ).select_related("season", "division")
            self.stdout.write("Current Season Teams:\n")

        teams = teams.order_by("division__division", "team_name")

        current_division = None
        for team in teams:
            if team.division != current_division:
                current_division = team.division
                self.stdout.write(f"\n--- {current_division} ---")

            url = f"{base_url}/goalie-status/captain/{team.captain_access_code}/"
            self.stdout.write(f"{team.team_name}: {url}")

        self.stdout.write(f"\nTotal: {teams.count()} teams")
