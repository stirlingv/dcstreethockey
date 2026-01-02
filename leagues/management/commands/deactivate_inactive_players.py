from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Max, Q

from leagues.models import Player, Roster, Season


class Command(BaseCommand):
    help = (
        "Deactivate players who haven't been on any roster in the past N years. "
        "Players with 'exclude_from_auto_deactivation' checked will be skipped. "
        "Players on any current season roster are always skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--years",
            type=int,
            default=3,
            help="Number of years of inactivity before deactivation (default: 3)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deactivated without making changes",
        )
        parser.add_argument(
            "--include-non-goalies",
            action="store_true",
            help="Include all players, not just goalies",
        )

    def handle(self, *args, **options):
        years = options["years"]
        dry_run = options["dry_run"]
        include_non_goalies = options["include_non_goalies"]
        cutoff_year = date.today().year - years

        self.stdout.write(
            f"Looking for players inactive since {cutoff_year} ({years} years)..."
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        # Get players on current season rosters (these should never be deactivated)
        current_season_players = set(
            Roster.objects.filter(team__season__is_current_season=True).values_list(
                "player_id", flat=True
            )
        )
        self.stdout.write(
            f"Found {len(current_season_players)} players on current season rosters (protected)"
        )

        # Get all active players who are NOT excluded from auto-deactivation
        players_query = Player.objects.filter(
            is_active=True,
            exclude_from_auto_deactivation=False,
        )

        # Optionally filter to only goalies (players who have ever played goalie)
        if not include_non_goalies:
            players_query = players_query.filter(
                Q(roster__position1=4) | Q(roster__position2=4)
            ).distinct()

        deactivated_count = 0
        skipped_count = 0

        for player in players_query:
            # Skip players on current season rosters
            if player.id in current_season_players:
                skipped_count += 1
                continue

            # Find the most recent season year this player was on a roster
            most_recent = Roster.objects.filter(player=player).aggregate(
                max_year=Max("team__season__year")
            )
            most_recent_year = most_recent.get("max_year")

            if most_recent_year is None or most_recent_year < cutoff_year:
                # Player hasn't been on a roster in N+ years (or never)
                years_inactive = (
                    "never rostered"
                    if most_recent_year is None
                    else f"last active {most_recent_year}"
                )

                if dry_run:
                    self.stdout.write(
                        f"  Would deactivate: {player} ({years_inactive})"
                    )
                else:
                    player.is_active = False
                    player.save(update_fields=["is_active"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Deactivated: {player} ({years_inactive})"
                        )
                    )
                deactivated_count += 1
            else:
                skipped_count += 1

        action = "Would deactivate" if dry_run else "Deactivated"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{action} {deactivated_count} players. "
                f"Skipped {skipped_count} active players."
            )
        )

        # Show players protected from auto-deactivation
        protected = Player.objects.filter(
            is_active=True, exclude_from_auto_deactivation=True
        )
        if protected.exists():
            self.stdout.write(
                f"\n{protected.count()} players are protected from auto-deactivation:"
            )
            for p in protected[:10]:  # Show first 10
                self.stdout.write(f"  - {p}")
            if protected.count() > 10:
                self.stdout.write(f"  ... and {protected.count() - 10} more")
