from __future__ import annotations

import datetime

from django.core.management.base import BaseCommand

from leagues.models import MatchUp, Team


class Command(BaseCommand):
    help = "List captain goalie update URLs for all active teams with upcoming games"

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
            help="Show all active teams, not just teams with upcoming games",
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
            today = datetime.date.today()
            # Show teams that have at least one upcoming matchup scheduled.
            # This is reliable regardless of how is_current_season is set on
            # the season, and naturally handles overlapping seasons.
            team_ids_with_games = MatchUp.objects.filter(
                week__date__gte=today
            ).values_list("awayteam_id", "hometeam_id")
            # Flatten the id pairs into a unique set.
            ids = {pk for pair in team_ids_with_games for pk in pair}
            teams = Team.objects.filter(pk__in=ids, is_active=True).select_related(
                "season", "division"
            )
            self.stdout.write("Teams with upcoming games:\n")

        teams = teams.order_by("division__division", "team_name")

        current_division = None
        for team in teams:
            if team.division != current_division:
                current_division = team.division
                self.stdout.write(f"\n--- {current_division} ---")

            url = f"{base_url}/goalie-status/captain/{team.captain_access_code}/"
            self.stdout.write(f"  {team.team_name} ({team.season}): {url}")

        self.stdout.write(f"\nTotal: {teams.count()} teams")
