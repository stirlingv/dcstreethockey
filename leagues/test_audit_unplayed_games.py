"""Tests for the audit_unplayed_games management command: past games with
no stats, and what the rest of the schedule says happened to them."""

import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from leagues.management.commands.audit_unplayed_games import (
    CANCEL_NEVER_PLAYED,
    CANCEL_RESCHEDULED,
    LOOK,
    RECENT,
    audit_unplayed_games,
)
from leagues.models import Division, MatchUp, Player, Season, Stat, Team, Week

TODAY = datetime.date(2026, 11, 5)


class AuditUnplayedGamesTest(TestCase):
    def setUp(self):
        self.season = Season.objects.create(year=2026, season_type=3)
        self.division = Division.objects.create(division=3)
        self.teams = [
            Team.objects.create(
                team_name=name,
                team_color="Blue",
                division=self.division,
                season=self.season,
                is_active=True,
            )
            for name in ("A", "B", "C", "D")
        ]
        self.player = Player.objects.create(first_name="Pat", last_name="Player")
        # A future game keeps the season current.
        self._game(datetime.date(2026, 11, 11), 0, 1)

    def _week(self, day):
        week, _ = Week.objects.get_or_create(
            division=self.division, season=self.season, date=day
        )
        return week

    def _game(self, day, home, away, played=False, **kwargs):
        game = MatchUp.objects.create(
            week=self._week(day),
            time=datetime.time(19, 0),
            hometeam=self.teams[home],
            awayteam=self.teams[away],
            **kwargs,
        )
        if played:
            Stat.objects.create(
                matchup=game, team=self.teams[home], player=self.player, goals=2
            )
            Stat.objects.create(
                matchup=game, team=self.teams[away], player=self.player, goals=1
            )
        return game

    def _rows(self, **kwargs):
        return audit_unplayed_games(today=TODAY, **kwargs)

    def test_played_cancelled_and_future_games_are_not_listed(self):
        self._game(datetime.date(2026, 9, 2), 0, 1, played=True)
        self._game(datetime.date(2026, 9, 9), 0, 1, is_cancelled=True)
        week = self._week(datetime.date(2026, 9, 16))
        week.is_cancelled = True
        week.save()
        self._game(datetime.date(2026, 9, 16), 2, 3)
        self.assertEqual(self._rows(), [])

    def test_rescheduled_when_the_pair_played_again_later(self):
        rained = self._game(datetime.date(2026, 9, 2), 0, 1)
        self._game(datetime.date(2026, 10, 7), 1, 0, played=True)
        (row,) = self._rows()
        self.assertEqual(row["game"], rained)
        self.assertEqual(row["suggestion"], CANCEL_RESCHEDULED)
        self.assertEqual(row["later_played_dates"], [datetime.date(2026, 10, 7)])
        self.assertIn("played again on Oct 7", row["why"])

    def test_whole_night_without_stats_looks_like_a_rain_out(self):
        self._game(datetime.date(2026, 9, 2), 0, 1)
        self._game(datetime.date(2026, 9, 2), 2, 3)
        rows = self._rows()
        self.assertEqual([r["suggestion"] for r in rows], [CANCEL_NEVER_PLAYED] * 2)
        self.assertIn("none of the 2", rows[0]["why"])
        self.assertEqual((rows[0]["night_games"], rows[0]["night_played"]), (2, 0))

    def test_pair_that_already_played_the_usual_number_did_not_need_it(self):
        # Every pair has played twice; this unplayed game would have been a
        # third meeting for A and B, which the schedule didn't need.
        for day in (datetime.date(2026, 9, 2), datetime.date(2026, 9, 16)):
            self._game(day, 0, 1, played=True)
            self._game(day, 2, 3, played=True)
        for day in (datetime.date(2026, 9, 9), datetime.date(2026, 9, 23)):
            self._game(day, 0, 2, played=True)
            self._game(day, 1, 3, played=True)
        self._game(datetime.date(2026, 9, 30), 0, 1)
        self._game(datetime.date(2026, 9, 30), 2, 3, played=True)
        (row,) = self._rows()
        self.assertEqual(row["suggestion"], CANCEL_NEVER_PLAYED)
        self.assertEqual((row["pair_played"], row["typical_pair_played"]), (2, 2))

    def test_lone_gap_on_a_played_night_needs_a_look(self):
        self._game(datetime.date(2026, 9, 2), 0, 1)
        self._game(datetime.date(2026, 9, 2), 2, 3, played=True)
        self._game(datetime.date(2026, 9, 9), 2, 3, played=True)
        (row,) = self._rows()
        self.assertEqual(row["suggestion"], LOOK)
        self.assertIn("1 of 2 games that night has stats", row["why"])

    def test_a_game_from_this_week_is_only_waiting_for_its_stats(self):
        self._game(datetime.date(2026, 11, 4), 0, 1)
        self._game(datetime.date(2026, 11, 4), 2, 3)
        rows = self._rows()
        self.assertEqual([r["suggestion"] for r in rows], [RECENT, RECENT])
        self.assertIn("1 day(s) ago", rows[0]["why"])

    def test_one_meeting_each_is_not_enough_to_call_a_game_surplus(self):
        self._game(datetime.date(2026, 9, 2), 0, 1, played=True)
        self._game(datetime.date(2026, 9, 2), 2, 3, played=True)
        self._game(datetime.date(2026, 9, 9), 0, 1)
        self._game(datetime.date(2026, 9, 9), 2, 3, played=True)
        (row,) = self._rows()
        self.assertEqual(row["suggestion"], LOOK)

    def test_notes_are_quoted(self):
        self._game(datetime.date(2026, 9, 2), 0, 1, notes=" rained out ")
        self._game(datetime.date(2026, 9, 2), 2, 3)
        self.assertIn('notes: "rained out"', self._rows()[0]["why"])

    def test_only_seasons_being_played_unless_asked(self):
        old = Season.objects.create(year=2024, season_type=3)
        week = Week.objects.create(
            division=self.division, season=old, date=datetime.date(2024, 9, 4)
        )
        MatchUp.objects.create(
            week=week,
            time=datetime.time(19, 0),
            hometeam=self.teams[0],
            awayteam=self.teams[1],
        )
        self.assertEqual(self._rows(), [])
        self.assertEqual(len(self._rows(all_seasons=True)), 1)

    def test_command_prints_games_by_date_with_a_summary(self):
        self._game(datetime.date(2026, 9, 2), 0, 1)
        self._game(datetime.date(2026, 9, 2), 2, 3)
        out = StringIO()
        with self.settings(USE_TZ=False):
            call_command("audit_unplayed_games", stdout=out)
        text = out.getvalue()
        self.assertIn("Wednesday, September 2, 2026", text)
        self.assertIn("B at A", text)
        self.assertIn(CANCEL_NEVER_PLAYED, text)
        self.assertIn("  2  total", text)

    def test_command_with_nothing_to_report(self):
        out = StringIO()
        call_command("audit_unplayed_games", stdout=out)
        self.assertIn("No past games are missing stats", out.getvalue())
