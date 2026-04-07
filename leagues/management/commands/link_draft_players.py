"""
Management command to link SeasonSignup records to existing Player records and
set is_returning based on Wednesday Draft League roster history.

Matching strategy (in priority order):
  1. Exact email match against Player.email
  2. Exact name match (case-insensitive first + last) when only one Player
     matches — covers players whose email has changed over the years
  3. No match — genuinely new players, left unlinked

The command is idempotent: already-linked signups are skipped unless --force
is passed. Safe to re-run locally and push results to the hosted DB.

Usage:
    python manage.py link_draft_players                  # Spring 2026 (season 120)
    python manage.py link_draft_players --season-id 120
    python manage.py link_draft_players --force          # re-evaluate all signups
    python manage.py link_draft_players --dry-run        # preview without saving
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from leagues.models import Division, DraftSession, Player, Season, SeasonSignup


class Command(BaseCommand):
    help = "Link SeasonSignup records to Player records and set is_returning."

    def add_arguments(self, parser):
        parser.add_argument(
            "--season-id",
            type=int,
            help="Season PK to process (default: most recent season with a DraftSession)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-evaluate signups that already have linked_player set.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would happen without writing to the database.",
        )

    def handle(self, *args, **options):
        season = self._get_season(options["season_id"])
        force = options["force"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Season: {season} (pk={season.pk})")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved."))

        signups = season.signups.select_related("linked_player").all()
        if not force:
            signups = signups.filter(linked_player__isnull=True)

        signups = list(signups)
        self.stdout.write(f"Evaluating {len(signups)} signup(s) (force={force})\n")

        if not signups:
            self.stdout.write("Nothing to do.")
            return

        # Pre-build a lookup of all Player emails for fast matching
        player_by_email = {
            p.email.lower(): p
            for p in Player.objects.exclude(email="").exclude(email=None)
        }

        wednesday_div = Division.objects.get(division=3)

        results = {"email": [], "name": [], "ambiguous": [], "new": []}

        for signup in signups:
            player, match_type = self._find_player(signup, player_by_email)
            if match_type == "ambiguous":
                results["ambiguous"].append((signup, None))
                continue
            if player is None:
                results["new"].append(signup)
                continue

            is_returning = self._has_wednesday_history(player, wednesday_div)
            results[match_type].append((signup, player, is_returning))

        self._print_report(results)

        if dry_run:
            return

        with transaction.atomic():
            for signup, player, is_returning in results["email"] + results["name"]:
                signup.linked_player = player
                signup.is_returning = is_returning
                signup.save(update_fields=["linked_player", "is_returning"])

        total_linked = len(results["email"]) + len(results["name"])
        self.stdout.write(
            self.style.SUCCESS(
                f"\nLinked {total_linked} signup(s). {len(results['new'])} new player(s) left unlinked."
            )
        )
        if results["ambiguous"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(results['ambiguous'])} ambiguous name match(es) — link manually in the admin."
                )
            )

    # -------------------------------------------------------------------------

    def _get_season(self, season_id):
        if season_id:
            try:
                return Season.objects.get(pk=season_id)
            except Season.DoesNotExist:
                raise CommandError(f"Season {season_id} not found.")

        # Default: most recent season that has a DraftSession
        season = (
            Season.objects.filter(draft_session__isnull=False)
            .order_by("-year", "-season_type")
            .first()
        )
        if not season:
            raise CommandError(
                "No season with a DraftSession found. Pass --season-id explicitly."
            )
        return season

    def _find_player(self, signup, player_by_email):
        """
        Return (Player, match_type) or (None, 'new') or (None, 'ambiguous').
        match_type is 'email' or 'name'.
        """
        # 1. Email match
        player = player_by_email.get(signup.email.lower())
        if player:
            return player, "email"

        # 2. Name match — only safe when exactly one Player has that name
        name_hits = Player.objects.filter(
            first_name__iexact=signup.first_name,
            last_name__iexact=signup.last_name,
        )
        count = name_hits.count()
        if count == 1:
            return name_hits.first(), "name"
        if count > 1:
            return None, "ambiguous"

        return None, "new"

    def _has_wednesday_history(self, player, wednesday_div):
        """True if the player has any Roster record in the Wednesday Draft League."""
        return player.roster_set.filter(team__division=wednesday_div).exists()

    def _print_report(self, results):
        if results["email"]:
            self.stdout.write(f"Email matches ({len(results['email'])}):")
            for signup, player, is_returning in results["email"]:
                ret = "returning" if is_returning else "new to Wed draft"
                self.stdout.write(
                    f"  {signup.first_name} {signup.last_name} → Player pk={player.pk} [{ret}]"
                )

        if results["name"]:
            self.stdout.write(
                f"\nName matches ({len(results['name'])}) — email changed:"
            )
            for signup, player, is_returning in results["name"]:
                ret = "returning" if is_returning else "new to Wed draft"
                self.stdout.write(
                    f"  {signup.first_name} {signup.last_name}"
                    f"  (signup: {signup.email} | player on file: {player.email})"
                    f" → Player pk={player.pk} [{ret}]"
                )

        if results["ambiguous"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\nAmbiguous — multiple players share this name (link manually):"
                )
            )
            for signup, _ in results["ambiguous"]:
                self.stdout.write(
                    f"  {signup.first_name} {signup.last_name} <{signup.email}>"
                )

        if results["new"]:
            self.stdout.write(
                f"\nNew players — no match found ({len(results['new'])}):"
            )
            for signup in results["new"]:
                self.stdout.write(
                    f"  {signup.first_name} {signup.last_name} <{signup.email}>"
                )
