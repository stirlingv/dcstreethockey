"""
Management command to seed a realistic Wednesday Draft League test scenario.

Creates (or resets) a test DraftSession with signups, teams, and captain
assignments so you can run through the full draft flow locally.

Usage:
    python manage.py seed_draft_test          # create fresh test data
    python manage.py seed_draft_test --reset  # wipe existing test data first
"""

import random
from django.core.management.base import BaseCommand
from django.db import transaction

from leagues.models import (
    Division,
    DraftPick,
    DraftRound,
    DraftSession,
    DraftTeam,
    Player,
    Season,
    SeasonSignup,
    Stat,
    Team,
)


# ---------------------------------------------------------------------------
# Fake player data — 8 teams × 12 players = 96 total (88 players + 8 goalies)
# ---------------------------------------------------------------------------

# (first_name, last_name, primary_position)
# Positions: 1=Center, 2=Wing, 3=Defense
PLAYERS = [
    # ── Centers ──────────────────────────────────────────────────────────────
    ("Alex", "Carter", 1),
    ("Casey", "Brooks", 1),
    ("Drew", "Simmons", 1),
    ("Reese", "Coleman", 1),
    ("Parker", "Barker", 1),
    ("Peyton", "Stone", 1),
    ("River", "Knight", 1),
    ("Rowan", "Holt", 1),
    ("Jamie", "Ellis", 1),
    ("Devon", "Price", 1),
    ("Robin", "Fox", 1),
    ("Corey", "Hunt", 1),
    ("Oakley", "Lane", 1),
    ("Teagan", "York", 1),
    ("Clem", "Gray", 1),
    ("Joss", "Mills", 1),
    ("Noel", "Palmer", 1),
    ("Wren", "Flores", 1),
    ("Bex", "Patterson", 1),
    ("Tai", "Monroe", 1),
    ("Penn", "Nguyen", 1),
    ("Scout", "Lawson", 1),
    ("True", "Ingram", 1),
    ("Rebel", "Estrada", 1),
    ("Bay", "Castillo", 1),
    ("Ora", "Romero", 1),
    ("Pax", "Torres", 1),
    ("Lux", "Reyes", 1),
    ("Greer", "Santiago", 1),
    ("Haven", "Burke", 1),
    # ── Wings ────────────────────────────────────────────────────────────────
    ("Jordan", "Murphy", 2),
    ("Morgan", "Hayes", 2),
    ("Avery", "Griffin", 2),
    ("Blake", "Pearce", 2),
    ("Sage", "Fletcher", 2),
    ("Cameron", "Walsh", 2),
    ("Logan", "Webb", 2),
    ("Emery", "Sharp", 2),
    ("Phoenix", "Rhodes", 2),
    ("Hayden", "Cole", 2),
    ("Sam", "Reed", 2),
    ("Jaden", "Grant", 2),
    ("Jules", "Dean", 2),
    ("Lennox", "Park", 2),
    ("Sutton", "Ray", 2),
    ("Waverly", "Lee", 2),
    ("Zion", "King", 2),
    ("Flynn", "Wood", 2),
    ("Merritt", "Cruz", 2),
    ("Sloane", "Spencer", 2),
    ("Milo", "Guerrero", 2),
    ("Shay", "Pacheco", 2),
    ("Xan", "Espinoza", 2),
    ("Cade", "Figueroa", 2),
    ("Lane", "Morales", 2),
    ("Tatum", "Nash", 2),
    ("Kit", "Ross", 2),
    ("Remy", "Clay", 2),
    ("Charlie", "Bell", 2),
    ("Tanner", "Wade", 2),
    # ── Defense ──────────────────────────────────────────────────────────────
    ("Taylor", "Bennett", 3),
    ("Riley", "Foster", 3),
    ("Quinn", "Warren", 3),
    ("Finley", "Hudson", 3),
    ("Skyler", "Gibson", 3),
    ("Harper", "Marsh", 3),
    ("Dakota", "Cross", 3),
    ("Spencer", "Crane", 3),
    ("Elliot", "Banks", 3),
    ("Sam", "Fox", 3),
    ("Robin", "Gray", 3),
    ("Devon", "Wade", 3),
    ("Jamie", "Hill", 3),
    ("Phoenix", "Stone", 3),
    ("Corey", "Park", 3),
    ("Hayden", "Mills", 3),
    ("Jules", "Webb", 3),
    ("Lennox", "Cross", 3),
    ("Sutton", "Lee", 3),
    ("Waverly", "King", 3),
    ("Merritt", "Fox", 3),
    ("Sloane", "Torres", 3),
    ("Tatum", "Burke", 3),
    ("Cade", "Ross", 3),
    ("Lane", "Cruz", 3),
    ("Noel", "Estrada", 3),
    ("Haven", "Wade", 3),
    ("Pax", "Reyes", 3),
]

GOALIES = [
    ("Pat", "Rourke"),
    ("Sam", "Ortega"),
    ("Jamie", "Lindqvist"),
    ("Chris", "Stamos"),
    ("Terry", "Nakamura"),
    ("Jesse", "Vance"),
    ("Drew", "Kim"),
    ("Jordan", "Chen"),
]

# Captain interest spread — realistic distribution
CAPTAIN_POOL = [
    SeasonSignup.CAPTAIN_YES,
    SeasonSignup.CAPTAIN_OVERDUE,
    SeasonSignup.CAPTAIN_OVERDUE,
    SeasonSignup.CAPTAIN_LAST_RESORT,
    SeasonSignup.CAPTAIN_LAST_RESORT,
    SeasonSignup.CAPTAIN_NO,
    SeasonSignup.CAPTAIN_NO,
    SeasonSignup.CAPTAIN_NO,
]


class Command(BaseCommand):
    help = "Seed a Wednesday Draft League test scenario for local testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing test data for the test season before seeding.",
        )
        parser.add_argument(
            "--season-id",
            type=int,
            default=None,
            help="Use a specific Season ID instead of creating a new one.",
        )
        parser.add_argument(
            "--completed",
            action="store_true",
            help=(
                "Simulate a fully completed draft so you can test Finalize Draft. "
                "Also sets the test season as the active season."
            ),
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            season = self._get_or_create_season(options)

            if options["reset"]:
                self._reset(season)

            if DraftSession.objects.filter(season=season).exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"A DraftSession already exists for {season}. "
                        "Use --reset to wipe and reseed."
                    )
                )
                self._print_urls(DraftSession.objects.get(season=season), season)
                return

            signups = self._create_signups(season)
            self._create_historical_stats(signups)
            self._create_historical_adp_data(signups)
            session = self._create_session(season, signups)

            if options["completed"]:
                self._create_completed_draft(session, signups)
                self._set_active_season(season)

            self._print_urls(session, season)

    # ------------------------------------------------------------------

    def _get_or_create_season(self, options):
        if options["season_id"]:
            try:
                return Season.objects.get(pk=options["season_id"])
            except Season.DoesNotExist:
                self.stderr.write(f"Season {options['season_id']} not found.")
                raise SystemExit(1)

        season, created = Season.objects.get_or_create(
            season_type=1,  # Spring
            year=2099,  # Clearly a test year — won't clash with real data
            defaults={"is_current_season": False},
        )
        if created:
            self.stdout.write(f"Created test season: {season}")
        else:
            self.stdout.write(f"Using existing test season: {season}")
        return season

    def _reset(self, season):
        # Collect linked players BEFORE wiping signups so we can clean up stats
        linked_player_ids = list(
            SeasonSignup.objects.filter(season=season)
            .exclude(linked_player=None)
            .values_list("linked_player_id", flat=True)
        )

        try:
            session = DraftSession.objects.get(season=season)
            DraftPick.objects.filter(session=session).delete()
            DraftTeam.objects.filter(session=session).delete()
            DraftRound.objects.filter(session=session).delete()
            session.delete()
            self.stdout.write("Wiped existing DraftSession.")
        except DraftSession.DoesNotExist:
            pass

        SeasonSignup.objects.filter(season=season).delete()
        self.stdout.write("Wiped existing signups.")

        if linked_player_ids:
            Stat.objects.filter(player_id__in=linked_player_ids).delete()
            Player.objects.filter(pk__in=linked_player_ids).delete()
            self.stdout.write(
                f"Wiped {len(linked_player_ids)} test players and their stats."
            )

        # Wipe the two past test seasons (2097, 2098) and everything linked to them
        for yr in [2097, 2098]:
            try:
                past = Season.objects.get(season_type=1, year=yr)
                # Draft data must go before signups/season (PROTECT FKs)
                try:
                    past_session = DraftSession.objects.get(season=past)
                    DraftPick.objects.filter(session=past_session).delete()
                    DraftTeam.objects.filter(session=past_session).delete()
                    DraftRound.objects.filter(session=past_session).delete()
                    past_session.delete()
                except DraftSession.DoesNotExist:
                    pass
                SeasonSignup.objects.filter(season=past).delete()
                Team.objects.filter(season=past).delete()
                past.delete()
                self.stdout.write(f"Wiped test season {yr}.")
            except Season.DoesNotExist:
                pass

    def _create_signups(self, season):
        signups = []

        for i, (first, last, pos) in enumerate(PLAYERS):
            secondary = (pos % 3) + 1  # something different from primary
            s = SeasonSignup.objects.create(
                season=season,
                first_name=first,
                last_name=last,
                email=f"{first.lower()}.{last.lower()}@example.com",
                primary_position=pos,
                secondary_position=secondary,
                captain_interest=CAPTAIN_POOL[i % len(CAPTAIN_POOL)],
                is_returning=(i % 3 != 0),
            )
            signups.append(s)

        for first, last in GOALIES:
            s = SeasonSignup.objects.create(
                season=season,
                first_name=first,
                last_name=last,
                email=f"{first.lower()}.{last.lower()}@example.com",
                primary_position=SeasonSignup.POSITION_GOALIE,
                secondary_position=SeasonSignup.POSITION_ONE_THING,
                captain_interest=SeasonSignup.CAPTAIN_NO,
                is_returning=True,
            )
            signups.append(s)

        self.stdout.write(
            f"Created {len(signups)} signups "
            f"({len(PLAYERS)} players + {len(GOALIES)} goalies)."
        )
        return signups

    def _create_historical_stats(self, signups):
        """
        Create fake Wednesday League history so the draft board shows real stats.

        Non-goalies (~60%): one Stat row per season played (season totals).
        Goalies (all):      one Stat row per game so that GAA is calculable via
                            row count (matchup=None, each row = 1 game played).

        Uses two clearly-test past seasons (2097, 2098).
        """
        wed_div, _ = Division.objects.get_or_create(division=3)

        past_seasons = []
        for yr in [2097, 2098]:
            past_s, _ = Season.objects.get_or_create(
                season_type=1,
                year=yr,
                defaults={"is_current_season": False},
            )
            past_seasons.append(past_s)

        # 8 test teams per past season
        past_teams = {ps.pk: [] for ps in past_seasons}
        for idx in range(1, 9):
            for ps in past_seasons:
                team, _ = Team.objects.get_or_create(
                    team_name=f"Test Draft Team {idx}",
                    season=ps,
                    defaults={
                        "division": wed_div,
                        "team_color": "#8b1a1a",
                        "is_active": False,
                    },
                )
                past_teams[ps.pk].append(team)

        # Realistic goals/assists ranges per position
        stat_ranges = {
            SeasonSignup.POSITION_CENTER: (5, 15, 8, 20),
            SeasonSignup.POSITION_WING: (4, 12, 5, 15),
            SeasonSignup.POSITION_DEFENSE: (1, 5, 4, 12),
        }

        # ~60% of non-goalies get historical player stats (season-total rows)
        non_goalies = [s for s in signups if not s.is_goalie]
        veterans = random.sample(non_goalies, int(len(non_goalies) * 0.6))

        for signup in veterans:
            player = Player.objects.create(
                first_name=signup.first_name,
                last_name=signup.last_name,
            )
            signup.linked_player = player
            signup.save(update_fields=["linked_player"])

            min_g, max_g, min_a, max_a = stat_ranges.get(
                signup.primary_position, (2, 8, 3, 10)
            )
            for ps in random.sample(past_seasons, random.randint(1, 2)):
                Stat.objects.create(
                    player=player,
                    team=random.choice(past_teams[ps.pk]),
                    matchup=None,
                    goals=random.randint(min_g, max_g),
                    assists=random.randint(min_a, max_a),
                    goals_against=0,
                )

        # All goalies get linked players + per-game stat rows so GAA is realistic.
        # Each row = 1 game (matchup=None); row count is used as the game denominator.
        goalies = [s for s in signups if s.is_goalie]
        for signup in goalies:
            player = Player.objects.create(
                first_name=signup.first_name,
                last_name=signup.last_name,
            )
            signup.linked_player = player
            signup.save(update_fields=["linked_player"])

            for ps in random.sample(past_seasons, random.randint(1, 2)):
                team = random.choice(past_teams[ps.pk])
                num_games = random.randint(10, 22)
                for _ in range(num_games):
                    Stat.objects.create(
                        player=player,
                        team=team,
                        matchup=None,
                        goals=0,
                        assists=0,
                        goals_against=random.randint(1, 6),
                    )

        self.stdout.write(
            f"Created historical stats for {len(veterans)} of {len(non_goalies)} players "
            f"and all {len(goalies)} goalies."
        )

    def _create_historical_adp_data(self, signups):
        """
        Create past DraftSession + DraftPick records so veteran players show
        ADP (average draft round) on the draft board.

        Uses the already-created 2097/2098 seasons.  Each veteran gets a past
        SeasonSignup (with the same linked_player) and is assigned to a random
        round — biased by position so centers go early, defence goes late.
        """
        num_teams = 8
        num_rounds = 12

        # Only players who already have a linked_player (created by _create_historical_stats)
        veterans = [s for s in signups if s.linked_player is not None]
        if not veterans:
            return

        # Earlier rounds for higher-demand positions
        position_round_range = {
            SeasonSignup.POSITION_CENTER: (1, 5),
            SeasonSignup.POSITION_WING: (2, 7),
            SeasonSignup.POSITION_DEFENSE: (4, 10),
            SeasonSignup.POSITION_GOALIE: (1, 3),  # goalies go very early
        }

        total_picks = 0

        for yr in [2097, 2098]:
            past_season = Season.objects.get(season_type=1, year=yr)

            # Create past-season signups, linked to the same Player objects
            past_signups = []
            for s in veterans:
                ps, _ = SeasonSignup.objects.get_or_create(
                    season=past_season,
                    first_name=s.first_name,
                    last_name=s.last_name,
                    defaults={
                        "email": s.email,
                        "primary_position": s.primary_position,
                        "secondary_position": s.secondary_position,
                        "captain_interest": SeasonSignup.CAPTAIN_NO,
                        "is_returning": True,
                        "linked_player": s.linked_player,
                    },
                )
                past_signups.append(ps)

            # Create a completed DraftSession for this past season
            session = DraftSession.objects.create(
                season=past_season,
                state=DraftSession.STATE_COMPLETE,
                num_teams=num_teams,
                num_rounds=num_rounds,
                signups_open=False,
            )

            # Use first 8 past signups as team captains with assigned positions
            captain_signups = past_signups[:num_teams]
            teams = []
            for i, cap in enumerate(captain_signups):
                team = DraftTeam.objects.create(
                    session=session,
                    captain=cap,
                    draft_position=i + 1,
                )
                teams.append(team)

            # Assign each veteran to a team/round, avoiding duplicate (team, round) slots
            used_slots = set()
            for ps in past_signups:
                lo, hi = position_round_range.get(ps.primary_position, (1, num_rounds))
                # Jitter the round so each draft year produces slightly different values
                round_num = random.randint(lo, min(hi + 1, num_rounds))
                available = [t for t in teams if (t.id, round_num) not in used_slots]
                if not available:
                    continue  # slot full — realistic, not everyone gets drafted every year
                team = random.choice(available)
                used_slots.add((team.id, round_num))
                DraftPick.objects.create(
                    session=session,
                    team=team,
                    signup=ps,
                    round_number=round_num,
                    pick_number=team.draft_position - 1,
                )
                total_picks += 1

        self.stdout.write(
            f"Created {total_picks} historical draft picks across 2097/2098 for ADP data."
        )

    def _create_session(self, season, signups):
        num_teams = 8
        num_rounds = 12  # 96 players / 8 teams = 12 rounds

        session = DraftSession.objects.create(
            season=season,
            state=DraftSession.STATE_SETUP,
            num_teams=num_teams,
            num_rounds=num_rounds,
            signups_open=True,
        )

        # Create rounds — make round 11 re-randomized (mirrors real-league practice)
        for r in range(1, num_rounds + 1):
            DraftRound.objects.create(
                session=session,
                round_number=r,
                order_type=DraftRound.ORDER_RANDOMIZED
                if r == 11
                else DraftRound.ORDER_SNAKE,
            )

        # Pick 8 captains from willing signups
        captain_candidates = [
            s
            for s in signups
            if s.captain_interest
            in (
                SeasonSignup.CAPTAIN_YES,
                SeasonSignup.CAPTAIN_OVERDUE,
            )
        ][:num_teams]

        if len(captain_candidates) < num_teams:
            # Fall back to any signup if not enough willing captains
            captain_candidates = signups[:num_teams]

        captain_rounds = random.sample(range(1, num_rounds + 1), num_teams)

        teams = []
        for i, captain_signup in enumerate(captain_candidates):
            team = DraftTeam.objects.create(
                session=session,
                captain=captain_signup,
                captain_draft_round=captain_rounds[i],
            )
            teams.append(team)

        self.stdout.write(
            f"Created DraftSession (pk={session.pk}) with {num_teams} teams, "
            f"{num_rounds} rounds."
        )
        self.stdout.write(
            f"  Round 11 is re-randomized. Captain rounds: "
            + ", ".join(f"{t.team_name}=R{t.captain_draft_round}" for t in teams)
        )
        return session

    def _create_completed_draft(self, session, signups):
        """
        Simulate a fully completed draft:
          - Assign random draft positions to all teams.
          - Create DraftPick records for every signup following snake-draft order,
            respecting captain auto-picks and the one-goalie-per-team rule.
          - Set session state to COMPLETE and close signups.
        """
        # Assign draft positions
        teams = list(session.teams.select_related("captain").order_by("pk"))
        positions = list(range(1, len(teams) + 1))
        random.shuffle(positions)
        for team, pos in zip(teams, positions):
            team.draft_position = pos
            team.save(update_fields=["draft_position"])
        teams.sort(key=lambda t: t.draft_position)

        # Round order types
        round_types = {r.round_number: r.order_type for r in session.rounds.all()}

        # Separate signups: captains are auto-picked, others fill the pool
        captain_ids = {t.captain_id for t in teams}
        pool = [s for s in signups if s.pk not in captain_ids]
        random.shuffle(pool)

        drafted = set()  # signup PKs already picked
        team_has_goalie = {t.pk: False for t in teams}
        pick_count = 0

        for r in range(1, session.num_rounds + 1):
            if round_types.get(r) == DraftRound.ORDER_RANDOMIZED:
                round_order = random.sample(teams, len(teams))
            elif r % 2 == 0:  # snake: even rounds reverse
                round_order = list(reversed(teams))
            else:
                round_order = list(teams)

            for pick_idx, team in enumerate(round_order):
                # Captain auto-pick: insert captain onto their own team
                if team.captain_draft_round == r and team.captain_id not in drafted:
                    DraftPick.objects.create(
                        session=session,
                        team=team,
                        signup_id=team.captain_id,
                        round_number=r,
                        pick_number=pick_idx,
                        is_auto_captain=True,
                    )
                    drafted.add(team.captain_id)
                    if team.captain.is_goalie:
                        team_has_goalie[team.pk] = True
                    pick_count += 1
                    continue

                # Regular pick — respect one-goalie-per-team rule
                remaining = [s for s in pool if s.pk not in drafted]
                if not remaining:
                    continue

                signup = None
                for candidate in remaining:
                    if candidate.is_goalie and team_has_goalie[team.pk]:
                        continue  # skip second goalie for this team
                    signup = candidate
                    break
                if signup is None:
                    signup = remaining[
                        0
                    ]  # fallback (shouldn't happen with 1 goalie/team)

                DraftPick.objects.create(
                    session=session,
                    team=team,
                    signup=signup,
                    round_number=r,
                    pick_number=pick_idx,
                )
                drafted.add(signup.pk)
                if signup.is_goalie:
                    team_has_goalie[team.pk] = True
                pick_count += 1

        session.state = DraftSession.STATE_COMPLETE
        session.signups_open = False
        session.save(update_fields=["state", "signups_open"])
        self.stdout.write(
            f"Simulated completed draft: {pick_count} picks across {session.num_teams} teams."
        )

    def _set_active_season(self, season):
        """Make the test season the active season, clearing the flag from all others."""
        previously_active = list(
            Season.objects.filter(is_current_season=True)
            .exclude(pk=season.pk)
            .values_list("season_type", "year")
        )
        Season.objects.exclude(pk=season.pk).filter(is_current_season=True).update(
            is_current_season=False
        )
        season.is_current_season = True
        season.save(update_fields=["is_current_season"])
        if previously_active:
            cleared = ", ".join(f"{y[1]}" for y in previously_active)
            self.stdout.write(f"Cleared active-season flag from: {cleared}.")
        self.stdout.write(self.style.SUCCESS(f"Set {season} as the active season."))

    def _print_urls(self, session, season):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(
            self.style.SUCCESS("  TEST URLS (all at http://localhost:8000)")
        )
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"  Signup form:      /draft/signup/{season.pk}/")
        self.stdout.write(f"  Spectator board:  /draft/{session.pk}/")
        self.stdout.write(f"  Captain portal:   /draft/{session.pk}/captains/")
        self.stdout.write(
            f"  Commissioner:     /draft/{session.pk}/commissioner/{session.commissioner_token}/"
        )
        self.stdout.write("")
        self.stdout.write("  Captain URLs:")
        for team in session.teams.select_related("captain").order_by("pk"):
            self.stdout.write(
                f"    {team.team_name:30s}  "
                f"/draft/{session.pk}/captain/{team.captain_token}/"
            )
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write("")
        self.stdout.write("  Admin (configure rounds, assign captain draft rounds):")
        self.stdout.write(
            f"  http://localhost:8000/admin/leagues/draftsession/{session.pk}/change/"
        )
        self.stdout.write("")
