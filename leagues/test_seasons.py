"""
Tests for leagues/seasons.py: which season each division is playing, worked
out from the schedule instead of the old hand-set ``is_current_season`` flag.
"""

import datetime

from django.test import TestCase

from leagues.models import Division, MatchUp, Season, Team, Week
from leagues.seasons import (
    active_season_ids,
    current_season,
    current_season_for_division,
    current_seasons,
    newest_active_season,
    newest_season,
    season_for_new_week,
)


class SeasonDerivationTest(TestCase):
    def setUp(self):
        self.d1 = Division.objects.create(division=1)
        self.d2 = Division.objects.create(division=2)
        self.fall = Season.objects.create(year=2026, season_type=3)
        self.winter = Season.objects.create(year=2026, season_type=4)
        self.teams = {}
        for season in (self.fall, self.winter):
            for division in (self.d1, self.d2):
                for name in ("A", "B"):
                    self.teams[(season.pk, division.pk, name)] = Team.objects.create(
                        team_name=f"{name} {division.division} {season.season_type}",
                        team_color="Blue",
                        division=division,
                        season=season,
                        is_active=True,
                    )

    def _game(self, season, division, on, cancelled=False, postseason=False):
        week, _ = Week.objects.get_or_create(division=division, season=season, date=on)
        return MatchUp.objects.create(
            week=week,
            time=datetime.time(19, 0),
            hometeam=self.teams[(season.pk, division.pk, "A")],
            awayteam=self.teams[(season.pk, division.pk, "B")],
            is_cancelled=cancelled,
            is_postseason=postseason,
        )

    def test_division_with_no_games_has_no_current_season(self):
        self.assertIsNone(current_season_for_division(self.d1.pk))
        self.assertEqual(current_seasons(), {})

    def test_finished_season_stays_current_until_a_newer_one_has_games(self):
        today = datetime.date(2026, 12, 1)
        self._game(self.fall, self.d1, datetime.date(2026, 11, 1))
        self.assertEqual(current_season_for_division(self.d1.pk, today), self.fall)
        self._game(self.winter, self.d1, datetime.date(2026, 11, 20))
        self.assertEqual(current_season_for_division(self.d1.pk, today), self.winter)

    def test_rain_delayed_championship_keeps_its_season_current(self):
        """The fall final was pushed past the winter opener. Fall stays
        current until the final is played; the day after, winter takes over
        with nothing for the admin to flip."""
        self._game(self.fall, self.d1, datetime.date(2026, 11, 1))
        final = self._game(
            self.fall, self.d1, datetime.date(2027, 1, 20), postseason=True
        )
        self._game(self.winter, self.d1, datetime.date(2027, 1, 10))
        self._game(self.winter, self.d1, datetime.date(2027, 1, 20))
        self._game(self.winter, self.d1, datetime.date(2027, 1, 27))

        on_final_day = datetime.date(2027, 1, 20)
        self.assertEqual(
            current_season_for_division(self.d1.pk, on_final_day), self.fall
        )
        day_after = datetime.date(2027, 1, 21)
        self.assertEqual(
            current_season_for_division(self.d1.pk, day_after), self.winter
        )

        # Cancelling the final (rather than playing it) also releases fall.
        final.is_cancelled = True
        final.save()
        self.assertEqual(
            current_season_for_division(self.d1.pk, on_final_day), self.winter
        )

    def test_each_division_is_worked_out_on_its_own(self):
        today = datetime.date(2027, 1, 15)
        self._game(self.fall, self.d1, datetime.date(2027, 1, 20))  # d1 still in fall
        self._game(self.winter, self.d2, datetime.date(2027, 1, 10))  # d2 moved on
        self.assertEqual(current_seasons(today), {1: self.fall, 2: self.winter})
        self.assertEqual(current_season(today), self.winter)

    def test_active_seasons_include_a_newer_season_with_only_teams(self):
        today = datetime.date(2026, 12, 1)
        self._game(self.fall, self.d1, datetime.date(2026, 11, 1))
        # Winter has teams (created in setUp) but no games yet.
        self.assertEqual(active_season_ids(today), {self.fall.pk, self.winter.pk})
        self.assertEqual(newest_active_season(today), self.winter)

    def test_active_seasons_fall_back_to_newest_when_nothing_is_scheduled(self):
        self.assertEqual(active_season_ids(), {self.winter.pk})

    def test_newest_season_ignores_games(self):
        self.assertEqual(newest_season(), self.winter)
        self.assertEqual(current_season(), self.winter)

    def test_season_for_new_week_is_newest_with_active_teams_in_division(self):
        self.assertEqual(season_for_new_week(self.d1.pk), self.winter)
        Team.objects.filter(season=self.winter, division=self.d1).update(
            is_active=False
        )
        self.assertEqual(season_for_new_week(self.d1.pk), self.fall)
        empty = Division.objects.create(division=3)
        self.assertEqual(season_for_new_week(empty.pk), self.winter)

    def test_the_old_flag_is_not_consulted(self):
        today = datetime.date(2026, 12, 1)
        self._game(self.fall, self.d1, datetime.date(2026, 11, 1))
        Season.objects.filter(pk=self.winter.pk).update(is_current_season=True)
        self.assertEqual(current_season_for_division(self.d1.pk, today), self.fall)
