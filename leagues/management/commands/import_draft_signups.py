"""
Management command to import Google Form signup responses into SeasonSignup
records and configure a DraftSession for the Wednesday Draft League.

Usage:
    python manage.py import_draft_signups
    python manage.py import_draft_signups --csv docs/my_responses.csv
    python manage.py import_draft_signups --season-id 120 --dry-run

Defaults to Season 120 (Spring 2026), 8 teams, 13 rounds, round 11 randomized.
Captains are auto-selected from willing registrants (YES > OVERDUE > LAST_RESORT),
sorted by submission date within each tier.

After running, set each DraftTeam.captain_draft_round in the admin before starting
the draw phase.
"""

import csv
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from leagues.models import DraftRound, DraftSession, DraftTeam, Season, SeasonSignup

DEFAULT_CSV = (
    "docs/2026 Spring Draft League Registration (Responses) - Form Responses 1.csv"
)
DEFAULT_SEASON_ID = 120

# CSV column header → strip whitespace when reading
COL_TIMESTAMP = "Timestamp"
COL_EMAIL = "Email Address"
COL_FIRST = "What's your FIRST name?"
COL_LAST = "What's your Last name?"
COL_PRIMARY = "Primary Position"
COL_SECONDARY = "Secondary Position"
COL_CAPTAIN = "Do you want to captain this Season? "
COL_NOTES = "Notes for the season such as out for travel, etc beyond a random week or 2 that most miss. "

PRIMARY_POS = {
    "Center": SeasonSignup.POSITION_CENTER,
    "Wing": SeasonSignup.POSITION_WING,
    "Defense": SeasonSignup.POSITION_DEFENSE,
    "Goalie": SeasonSignup.POSITION_GOALIE,
}

SECONDARY_POS = {
    **PRIMARY_POS,
    "I only do one thing, period!": SeasonSignup.POSITION_ONE_THING,
}

CAPTAIN_INTEREST = {
    "Yes for sure please so I control who I play with": SeasonSignup.CAPTAIN_YES,
    "I can as I'm overdue to captain/help out": SeasonSignup.CAPTAIN_OVERDUE,
    "Only if you can't find 8": SeasonSignup.CAPTAIN_LAST_RESORT,
    "Nope, lazy or don't know enough": SeasonSignup.CAPTAIN_NO,
    "": SeasonSignup.CAPTAIN_NO,
}

TIMESTAMP_FMT = "%m/%d/%Y %H:%M:%S"


class Command(BaseCommand):
    help = "Import Google Form draft signups and configure a DraftSession."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default=DEFAULT_CSV,
            help=f"Path to the CSV file (default: {DEFAULT_CSV})",
        )
        parser.add_argument(
            "--season-id",
            type=int,
            default=DEFAULT_SEASON_ID,
            help=f"Season PK to import into (default: {DEFAULT_SEASON_ID})",
        )
        parser.add_argument(
            "--num-teams",
            type=int,
            default=8,
            help="Number of teams in the draft (default: 8)",
        )
        parser.add_argument(
            "--num-rounds",
            type=int,
            default=13,
            help="Number of draft rounds (default: 13)",
        )
        parser.add_argument(
            "--random-round",
            type=int,
            default=11,
            help="Which round uses randomized order instead of snake (default: 11)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate without writing anything to the database.",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        season_id = options["season_id"]
        num_teams = options["num_teams"]
        num_rounds = options["num_rounds"]
        random_round = options["random_round"]
        dry_run = options["dry_run"]

        try:
            season = Season.objects.get(pk=season_id)
        except Season.DoesNotExist:
            raise CommandError(f"Season {season_id} not found.")

        self.stdout.write(f"Target season: {season} (pk={season.pk})")

        if DraftSession.objects.filter(season=season).exists():
            raise CommandError(
                f"A DraftSession already exists for {season}. "
                "Delete it first if you want to re-import."
            )

        rows = self._parse_csv(csv_path)
        self.stdout.write(f"Parsed {len(rows)} rows from {csv_path}")

        if dry_run:
            self._print_summary(rows, num_teams)
            self.stdout.write(self.style.WARNING("DRY RUN — no changes written."))
            return

        with transaction.atomic():
            signups = self._create_signups(season, rows)
            session = self._create_session(
                season, signups, num_teams, num_rounds, random_round
            )

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. {len(signups)} signups imported.")
        )
        self._print_urls(session)

    # -------------------------------------------------------------------------

    def _parse_csv(self, csv_path):
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except FileNotFoundError:
            raise CommandError(f"CSV file not found: {csv_path}")

    def _clean_name(self, first, last):
        """
        Fix submissions where the registrant put their full name in the first
        name field (e.g. first='David Gerber', last='Gerber' → first='David').
        """
        first = first.strip()
        last = last.strip()
        if first.lower().endswith(last.lower()) and first.lower() != last.lower():
            first = first[: -len(last)].strip()
        return first, last

    def _parse_row(self, row):
        first, last = self._clean_name(row[COL_FIRST], row[COL_LAST])
        primary_str = row[COL_PRIMARY].strip()
        secondary_str = row[COL_SECONDARY].strip()
        captain_str = row[COL_CAPTAIN].strip()

        primary = PRIMARY_POS.get(primary_str)
        if primary is None:
            raise CommandError(
                f"Unknown primary position '{primary_str}' for {first} {last}"
            )

        secondary = SECONDARY_POS.get(secondary_str)
        if secondary is None:
            raise CommandError(
                f"Unknown secondary position '{secondary_str}' for {first} {last}"
            )

        captain_interest = CAPTAIN_INTEREST.get(captain_str)
        if captain_interest is None:
            raise CommandError(
                f"Unknown captain interest '{captain_str}' for {first} {last}"
            )

        try:
            submitted_at = datetime.strptime(row[COL_TIMESTAMP].strip(), TIMESTAMP_FMT)
        except ValueError:
            submitted_at = None

        return {
            "first_name": first,
            "last_name": last,
            "email": row[COL_EMAIL].strip().lower(),
            "primary_position": primary,
            "secondary_position": secondary,
            "captain_interest": captain_interest,
            "notes": row[COL_NOTES].strip(),
            "submitted_at": submitted_at,
        }

    def _create_signups(self, season, rows):
        existing_emails = set(
            SeasonSignup.objects.filter(season=season).values_list("email", flat=True)
        )
        created = []
        skipped = 0

        for row in rows:
            if (
                not row.get(COL_EMAIL, "").strip()
                and not row.get(COL_FIRST, "").strip()
            ):
                continue  # skip blank rows
            data = self._parse_row(row)
            if data["email"] in existing_emails:
                self.stdout.write(
                    f"  skip (exists): {data['first_name']} {data['last_name']}"
                )
                skipped += 1
                continue

            signup = SeasonSignup.objects.create(
                season=season,
                first_name=data["first_name"],
                last_name=data["last_name"],
                email=data["email"],
                primary_position=data["primary_position"],
                secondary_position=data["secondary_position"],
                captain_interest=data["captain_interest"],
                notes=data["notes"],
            )
            # Preserve original submission timestamp (auto_now_add prevents direct assignment)
            if data["submitted_at"]:
                SeasonSignup.objects.filter(pk=signup.pk).update(
                    submitted_at=data["submitted_at"]
                )
            created.append(signup)
            self.stdout.write(
                f"  created: {signup.first_name} {signup.last_name} "
                f"({signup.get_primary_position_display()}, "
                f"captain={signup.get_captain_interest_display()})"
            )

        if skipped:
            self.stdout.write(f"  {skipped} existing signup(s) skipped.")

        # Reload to get the updated submitted_at timestamps
        return list(SeasonSignup.objects.filter(season=season))

    def _create_session(self, season, signups, num_teams, num_rounds, random_round):
        session = DraftSession.objects.create(
            season=season,
            num_teams=num_teams,
            num_rounds=num_rounds,
            state=DraftSession.STATE_SETUP,
            signups_open=False,
        )
        self.stdout.write(f"\nCreated DraftSession pk={session.pk}")

        # Create round configurations
        for r in range(1, num_rounds + 1):
            order = (
                DraftRound.ORDER_RANDOMIZED
                if r == random_round
                else DraftRound.ORDER_SNAKE
            )
            DraftRound.objects.create(session=session, round_number=r, order_type=order)
        self.stdout.write(
            f"Created {num_rounds} rounds (round {random_round} = randomized, rest = snake)"
        )

        # Select captains: YES first, then OVERDUE, then LAST_RESORT, sorted by
        # submitted_at within each tier. Stop once we have num_teams captains.
        willing = sorted(
            [s for s in signups if s.captain_interest < SeasonSignup.CAPTAIN_NO],
            key=lambda s: (s.captain_interest, s.submitted_at or datetime.max),
        )
        captains = willing[:num_teams]

        if len(captains) < num_teams:
            self.stdout.write(
                self.style.WARNING(
                    f"Only {len(captains)} willing captains found for {num_teams} teams. "
                    "Add more DraftTeams manually in the admin."
                )
            )

        self.stdout.write(f"\nAssigning {len(captains)} captains:")
        for i, signup in enumerate(captains, 1):
            team = DraftTeam.objects.create(session=session, captain=signup)
            self.stdout.write(
                f"  Team {i}: {signup.first_name} {signup.last_name} "
                f"({signup.get_captain_interest_display()}) — token: {team.captain_token}"
            )

        return session

    def _print_summary(self, rows, num_teams):
        parsed = [
            self._parse_row(r)
            for r in rows
            if r.get(COL_EMAIL, "").strip() or r.get(COL_FIRST, "").strip()
        ]
        from collections import Counter

        pos_counts = Counter(r["primary_position"] for r in parsed)
        cap_counts = Counter(r["captain_interest"] for r in parsed)

        self.stdout.write("\nPosition breakdown:")
        for pos, label in SeasonSignup.PRIMARY_POSITION_CHOICES:
            self.stdout.write(f"  {label}: {pos_counts.get(pos, 0)}")

        self.stdout.write("\nCaptain interest breakdown:")
        for val, label in SeasonSignup.CAPTAIN_INTEREST_CHOICES:
            self.stdout.write(f"  {label[:40]}: {cap_counts.get(val, 0)}")

        willing = sorted(
            [r for r in parsed if r["captain_interest"] < SeasonSignup.CAPTAIN_NO],
            key=lambda r: (r["captain_interest"], r["submitted_at"] or datetime.max),
        )
        self.stdout.write(f"\nWould-be captains (top {num_teams}):")
        for i, r in enumerate(willing[:num_teams], 1):
            self.stdout.write(f"  {i}. {r['first_name']} {r['last_name']}")

    def _print_urls(self, session):
        base = "http://localhost:8000"
        self.stdout.write("\n--- Draft URLs ---")
        self.stdout.write(f"  Spectator board : {base}/draft/{session.pk}/")
        self.stdout.write(
            f"  Commissioner    : {base}/draft/{session.pk}/commissioner/{session.commissioner_token}/"
        )
        self.stdout.write(f"  Captain portal  : {base}/draft/{session.pk}/captains/")
        self.stdout.write(
            "\nNext steps:\n"
            "  1. Admin → DraftSession → set captain_draft_round for each team\n"
            "  2. Admin → SeasonSignup → mark returning players and link Player records\n"
            "  3. Hit the commissioner URL above to draw positions and start the draft"
        )
