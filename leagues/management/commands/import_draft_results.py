"""
Management command to import completed draft boards (Google Sheets grid
export) as historical DraftSession/DraftPick records.

This feeds the ADP statistic shown on the draft board: the system averages
each player's DraftPick.round_number across all sessions where their
SeasonSignup.linked_player matches.

Expected draft-board CSV format (the "Draft Board" tab export):
  Row 0 : <blank>, <captain1_name>, <captain2_name>, ...
  Row 1 : optional metadata row (skipped automatically)
  Row 2 : "Captain:", ...
  Rows  : <round_num>, <pick_col1>, ..., <pick_colN>  (one row per round)
  Cells : "LastName, FirstName"  (may have extra whitespace or irregular case)
  Later rows contain schedule/color data and are ignored.

Optional companion registration CSV (same format as the Google Form export):
  Columns: Timestamp, Email Address, What's your FIRST name?,
           What's your Last name?, ...
  Providing this file enables email-first player matching, which is more
  reliable than name matching alone and resolves capitalisation mismatches
  (e.g. "ONeill" → email → Player "O'Neill").

Usage:
    # Dry run to preview matching before committing
    python manage.py import_draft_results \\
        --csv "docs/2025 Fall Draft Board - Draft Board.csv" \\
        --roster-csv "docs/2025 Fall Draft League Registration (Responses) - Form Responses 1.csv" \\
        --season-id 119 \\
        --dry-run

    # Full import with auto-creation of unmatched players
    python manage.py import_draft_results \\
        --csv "docs/2025 Fall Draft Board - Draft Board.csv" \\
        --roster-csv "docs/2025 Fall Draft League Registration (Responses) - Form Responses 1.csv" \\
        --season-id 119 \\
        --create-players
"""

import csv
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from leagues.models import (
    DraftPick,
    DraftRound,
    DraftSession,
    DraftTeam,
    Player,
    Season,
    SeasonSignup,
)

DEFAULT_RANDOM_ROUND = 11

# Registration CSV column headers (same across all seasons)
COL_EMAIL = "Email Address"
COL_FIRST = "What's your FIRST name?"
COL_LAST = "What's your Last name?"


class Command(BaseCommand):
    help = (
        "Import a completed draft-board CSV as historical DraftSession/DraftPick "
        "records so returning players show ADP on the live draft board."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            dest="csv_path",
            required=True,
            help="Path to the draft board grid CSV.",
        )
        parser.add_argument(
            "--roster-csv",
            dest="roster_csv_path",
            default=None,
            help=(
                "Path to the companion registration-form CSV.  When provided, "
                "player matching uses email first (more reliable than name alone)."
            ),
        )
        parser.add_argument(
            "--season-id",
            type=int,
            required=True,
            help="Season PK that this historical draft belongs to.",
        )
        parser.add_argument(
            "--random-round",
            type=int,
            default=DEFAULT_RANDOM_ROUND,
            help=f"Which round was re-randomized (default: {DEFAULT_RANDOM_ROUND})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and match without writing anything to the database.",
        )
        parser.add_argument(
            "--create-players",
            action="store_true",
            help=(
                "Create Player records for players whose name/email cannot be "
                "matched to an existing Player.  Without this flag they are "
                "skipped and reported for manual admin review."
            ),
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        roster_csv_path = options["roster_csv_path"]
        season_id = options["season_id"]
        random_round = options["random_round"]
        dry_run = options["dry_run"]
        create_players = options["create_players"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN — no changes will be written.\n")
            )

        season = self._get_season(season_id)
        self.stdout.write(f"Season: {season} (pk={season.pk})\n")

        if DraftSession.objects.filter(season=season).exists():
            raise CommandError(
                f"A DraftSession already exists for {season}.  "
                "Delete it first or use a different --season-id."
            )

        # Build name→email map from registration CSV if provided
        roster_map = {}
        if roster_csv_path:
            roster_map = self._parse_roster_csv(roster_csv_path)
            self.stdout.write(
                f"Loaded {len(roster_map)} name→email mappings from {roster_csv_path}\n"
            )

        captain_names, rounds = self._parse_board_csv(csv_path)
        num_teams = len(captain_names)
        num_rounds = len(rounds)
        self.stdout.write(
            f"Parsed {num_rounds} rounds × {num_teams} teams = "
            f"{num_rounds * num_teams} pick slots from {csv_path}\n"
        )

        # Build Player name index for fallback matching
        player_by_name = self._build_player_name_index()
        player_by_email = self._build_player_email_index()

        # Match captains (nickname/first-name only — informational, not required for ADP)
        captain_players = self._match_captains(
            captain_names, roster_map, player_by_name, player_by_email
        )

        # Match every player pick cell
        pick_matrix, match_report = self._match_picks(
            rounds,
            captain_names,
            roster_map,
            player_by_name,
            player_by_email,
            create_players,
            dry_run,
        )

        self._print_match_report(match_report)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDRY RUN complete — nothing written.")
            )
            return

        with transaction.atomic():
            session = self._create_session(
                season, captain_names, captain_players, num_rounds, random_round
            )
            pick_count = self._create_picks(
                session, captain_names, captain_players, pick_matrix, roster_map
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nImported {pick_count} picks into DraftSession pk={session.pk}.\n"
                f"Players without a linked_player will show no ADP — "
                f"link them via Admin → SeasonSignup or re-run with --create-players."
            )
        )

    # ------------------------------------------------------------------
    # CSV parsing
    # ------------------------------------------------------------------

    def _parse_roster_csv(self, path):
        """
        Parse a Google Form registration CSV.
        Returns {(first_lower, last_lower): email} for all rows.
        """
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except FileNotFoundError:
            raise CommandError(f"Roster CSV not found: {path}")

        roster_map = {}
        for row in rows:
            first = row.get(COL_FIRST, "").strip()
            last = row.get(COL_LAST, "").strip()
            email = row.get(COL_EMAIL, "").strip().lower()
            if not first or not last or not email:
                continue
            key = (first.lower(), last.lower())
            # If a player submitted multiple times keep the most recent (last row wins)
            roster_map[key] = email
        return roster_map

    def _parse_board_csv(self, csv_path):
        """
        Parse the draft board grid CSV.
        Returns (captain_names, rounds) where:
          captain_names : list of captain name strings from the header row
          rounds        : list of dicts {captain_name: (round_num, (first, last) | None)}
        """
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except FileNotFoundError:
            raise CommandError(f"Draft board CSV not found: {csv_path}")

        if not rows:
            raise CommandError("CSV is empty.")

        # Row 0: blank col, then captain names/nicknames
        header = rows[0]
        captain_names = [h.strip() for h in header[1:] if h.strip()]
        if not captain_names:
            raise CommandError("Could not find captain names in the first row.")

        # Collect pick rows: col 0 must be an integer (the round number)
        rounds = []
        for row in rows[1:]:
            if not row:
                continue
            round_cell = row[0].strip()
            if not re.match(r"^\d+$", round_cell):
                continue  # skip header, metadata, and schedule rows
            round_num = int(round_cell)
            picks = {}
            for i, cap_name in enumerate(captain_names):
                col = i + 1
                cell = row[col].strip() if col < len(row) else ""
                parsed = self._parse_name_cell(cell)
                picks[cap_name] = (round_num, parsed)
            rounds.append(picks)

        if not rounds:
            raise CommandError("No pick rows found — check the CSV format.")

        return captain_names, rounds

    def _parse_name_cell(self, cell):
        """
        Parse "LastName, FirstName" → (first, last).
        Returns None for blank or unparseable cells.
        Strips excess whitespace; preserves original casing for roster lookup.
        """
        cell = cell.strip()
        if not cell or "," not in cell:
            return None
        parts = cell.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip()
        if not first or not last:
            return None
        return first, last

    # ------------------------------------------------------------------
    # Player matching
    # ------------------------------------------------------------------

    def _build_player_name_index(self):
        """Return {(first_lower, last_lower): [Player, ...]} for all players."""
        index = {}
        for player in Player.objects.all():
            key = (player.first_name.strip().lower(), player.last_name.strip().lower())
            index.setdefault(key, []).append(player)
        return index

    def _build_player_email_index(self):
        """Return {email_lower: Player} for all players with an email on file."""
        return {
            p.email.strip().lower(): p
            for p in Player.objects.exclude(email="").exclude(email__isnull=True)
        }

    def _resolve_player(self, first, last, roster_map, player_by_name, player_by_email):
        """
        Attempt to match (first, last) to a Player record.

        Priority:
          1. Email match via roster_map → player_by_email  (most reliable)
          2. Exact name match (case-insensitive)           (fallback)

        Returns (Player | None, match_type) where match_type is one of:
          'email', 'name', 'ambiguous', 'new'
        """
        name_key = (first.strip().lower(), last.strip().lower())

        # 1. Email match via roster CSV
        email = roster_map.get(name_key)
        if email:
            player = player_by_email.get(email.lower())
            if player:
                return player, "email"
            # Email not in Player table — fall through to name match

        # 2. Name match
        hits = player_by_name.get(name_key, [])
        if len(hits) == 1:
            return hits[0], "name"
        if len(hits) > 1:
            return None, "ambiguous"

        return None, "new"

    def _match_captains(
        self, captain_names, roster_map, player_by_name, player_by_email
    ):
        """
        Try to match captain nicknames to Player records.
        Returns {cap_name: Player | None}.
        Unmatched captains are reported but don't block the import.
        """
        result = {}
        self.stdout.write("Captain matching:")
        for cap_name in captain_names:
            # Captains are often listed by nickname/first name only.
            # Try first-name-only lookup; if ambiguous, leave unlinked.
            first_lower = cap_name.strip().lower()
            candidates = [
                p
                for (fn, _), players in player_by_name.items()
                if fn == first_lower
                for p in players
            ]
            unique = list({p.pk: p for p in candidates}.values())

            if len(unique) == 1:
                result[cap_name] = unique[0]
                self.stdout.write(
                    f"  {cap_name} → {unique[0].first_name} {unique[0].last_name} (pk={unique[0].pk})"
                )
            elif len(unique) > 1:
                result[cap_name] = None
                self.stdout.write(
                    self.style.WARNING(
                        f"  {cap_name} → AMBIGUOUS ({len(unique)} players share this first name)"
                    )
                )
            else:
                result[cap_name] = None
                self.stdout.write(
                    self.style.WARNING(
                        f"  {cap_name} → NOT FOUND (link manually in admin)"
                    )
                )
        return result

    def _match_picks(
        self,
        rounds,
        captain_names,
        roster_map,
        player_by_name,
        player_by_email,
        create_players,
        dry_run,
    ):
        """
        Resolve every pick cell to a Player.
        Returns (pick_matrix, match_report).
        """
        pick_matrix = {}
        match_report = {"email": [], "name": [], "ambiguous": [], "new": []}
        created_players = (
            {}
        )  # (first_lower, last_lower) → Player, avoids re-creating within CSV

        for round_picks in rounds:
            for cap_name, (round_num, name_tuple) in round_picks.items():
                if name_tuple is None:
                    continue
                first, last = name_tuple
                player, status = self._resolve_player(
                    first, last, roster_map, player_by_name, player_by_email
                )

                if status == "new" and create_players and not dry_run:
                    key = (first.lower(), last.lower())
                    if key not in created_players:
                        email = roster_map.get(key)
                        player, _ = Player.objects.get_or_create(
                            first_name__iexact=first,
                            last_name__iexact=last,
                            defaults={
                                "first_name": first,
                                "last_name": last,
                                "email": email or "",
                                "is_active": True,
                            },
                        )
                        created_players[key] = player
                        # Register in indexes for any later duplicate cells
                        player_by_name.setdefault(key, []).append(player)
                        if email:
                            player_by_email[email] = player
                    else:
                        player = created_players[key]
                    status = "name"  # treat as matched for reporting

                pick_matrix[(round_num, cap_name)] = (first, last, player)
                match_report[status].append((round_num, cap_name, first, last, player))

        return pick_matrix, match_report

    def _print_match_report(self, match_report):
        counts = {k: len(v) for k, v in match_report.items()}
        total = sum(counts.values())
        self.stdout.write(
            f"\nPlayer matching ({total} picks): "
            f"{counts['email']} via email, "
            f"{counts['name']} via name, "
            f"{counts['ambiguous']} ambiguous, "
            f"{counts['new']} not found"
        )

        if match_report["ambiguous"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nAmbiguous (multiple players share this name — link manually):"
                )
            )
            for round_num, cap, first, last, _ in match_report["ambiguous"]:
                self.stdout.write(f"  R{round_num} / {cap}: {first} {last}")

        if match_report["new"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nNot found (skipped — use --create-players to auto-create):"
                )
            )
            for round_num, cap, first, last, _ in match_report["new"]:
                self.stdout.write(f"  R{round_num} / {cap}: {first} {last}")

    # ------------------------------------------------------------------
    # Database writes
    # ------------------------------------------------------------------

    def _get_season(self, season_id):
        try:
            return Season.objects.get(pk=season_id)
        except Season.DoesNotExist:
            raise CommandError(f"Season {season_id} not found.")

    def _create_session(
        self, season, captain_names, captain_players, num_rounds, random_round
    ):
        session = DraftSession.objects.create(
            season=season,
            num_teams=len(captain_names),
            num_rounds=num_rounds,
            state=DraftSession.STATE_COMPLETE,
            signups_open=False,
            finalized_at=timezone.now(),
        )
        self.stdout.write(f"\nCreated DraftSession pk={session.pk} (COMPLETE)")

        for r in range(1, num_rounds + 1):
            order_type = (
                DraftRound.ORDER_RANDOMIZED
                if r == random_round
                else DraftRound.ORDER_SNAKE
            )
            DraftRound.objects.create(
                session=session, round_number=r, order_type=order_type
            )

        for pos, cap_name in enumerate(captain_names, start=1):
            player = captain_players.get(cap_name)
            cap_signup = self._get_or_create_signup(season, player, cap_name, "")
            DraftTeam.objects.create(
                session=session,
                captain=cap_signup,
                team_name=f"{cap_name}'s Team",
                draft_position=pos,
            )

        self.stdout.write(f"Created {len(captain_names)} DraftTeam records.")
        return session

    def _get_or_create_signup(self, season, player, first_name, last_name, email=None):
        """Find or create a SeasonSignup for this season+player."""
        real_first = player.first_name if player else first_name
        real_last = player.last_name if player else last_name

        if player:
            existing = SeasonSignup.objects.filter(
                season=season, linked_player=player
            ).first()
            if existing:
                return existing

        signup_email = email or (
            player.email
            if (player and player.email)
            else f"{real_first.lower()}.{real_last.lower()}@import.local"
        )
        signup = SeasonSignup.objects.create(
            season=season,
            first_name=real_first,
            last_name=real_last,
            email=signup_email,
            primary_position=SeasonSignup.POSITION_CENTER,
            secondary_position=SeasonSignup.POSITION_ONE_THING,
            captain_interest=SeasonSignup.CAPTAIN_NO,
            is_returning=player is not None,
        )
        if player:
            signup.linked_player = player
            signup.save(update_fields=["linked_player"])
        return signup

    def _create_picks(
        self, session, captain_names, captain_players, pick_matrix, roster_map
    ):
        teams = {dt.team_name: dt for dt in session.teams.all()}
        pick_count = 0
        skipped = 0

        for (round_num, cap_name), (first, last, player) in sorted(pick_matrix.items()):
            if player is None:
                skipped += 1
                continue

            team = teams.get(f"{cap_name}'s Team")
            if team is None:
                self.stdout.write(
                    self.style.WARNING(f"  No team for {cap_name} — skipping")
                )
                continue

            name_key = (first.lower(), last.lower())
            email = roster_map.get(name_key) or (player.email if player.email else None)
            signup = self._get_or_create_signup(
                session.season, player, first, last, email
            )

            if DraftPick.objects.filter(session=session, signup=signup).exists():
                skipped += 1
                continue

            pick_number = captain_names.index(cap_name)
            matched_captain = captain_players.get(cap_name)
            if matched_captain is not None:
                is_captain_pick = player == matched_captain
            else:
                # Captain header wasn't resolved to a Player (ambiguous or
                # first-name-only like "Jesse", "Mike E", "Kenny").
                # Fall back: check whether the player's first name is a
                # case-insensitive prefix match against the header token —
                # catches "Kenny"→"Ken", "Mike E"→"Mike", "Jesse"→"Jesse".
                cap_prefix = cap_name.strip().split()[0].lower()
                p_first = player.first_name.strip().lower()
                is_captain_pick = cap_prefix.startswith(p_first) or p_first.startswith(
                    cap_prefix
                )
            DraftPick.objects.create(
                session=session,
                team=team,
                signup=signup,
                round_number=round_num,
                pick_number=pick_number,
                is_auto_captain=is_captain_pick,
            )
            pick_count += 1

        self.stdout.write(
            f"Created {pick_count} DraftPick records "
            f"({skipped} skipped — no match or duplicate)."
        )
        return pick_count
