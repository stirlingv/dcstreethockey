"""
Tests for leagues/results.py and leagues/signals.py: a game's result from
its score, and the standings rebuilt from every game in a season.
"""

import datetime

from django.test import TestCase

from leagues.models import (
    Division,
    MatchUp,
    Player,
    Season,
    Stat,
    Team,
    Team_Stat,
    Week,
)
from leagues.results import (
    game_result,
    recompute_team_stats,
    standings_recompute_deferred,
)


class ResultsFixture(TestCase):
    def setUp(self):
        self.season = Season.objects.create(year=2027, season_type=1)
        self.division = Division.objects.create(division=5)
        self.a, self.b, self.c = (
            Team.objects.create(
                team_name=name,
                team_color="Blue",
                division=self.division,
                season=self.season,
                is_active=True,
            )
            for name in ("Alpha", "Bravo", "Charlie")
        )
        self.player = Player.objects.create(first_name="Pat", last_name="Player")
        self.week = Week.objects.create(
            division=self.division, season=self.season, date=datetime.date(2027, 3, 1)
        )

    def _game(self, home, away, **kwargs):
        return MatchUp.objects.create(
            week=kwargs.pop("week", self.week),
            time=datetime.time(19, 0),
            hometeam=home,
            awayteam=away,
            **kwargs,
        )

    def _score(self, game, home_goals, away_goals):
        Stat.objects.filter(matchup=game).delete()
        if home_goals:
            Stat.objects.create(
                matchup=game, team=game.hometeam, player=self.player, goals=home_goals
            )
        if away_goals:
            Stat.objects.create(
                matchup=game, team=game.awayteam, player=self.player, goals=away_goals
            )

    def _record(self, team):
        row = Team_Stat.objects.get(
            team=team, season=self.season, division=self.division
        )
        return (row.win, row.otw, row.otl, row.loss, row.goals_for, row.goals_against)


class GameResultTest(ResultsFixture):
    def test_regulation_win(self):
        game = self._game(self.a, self.b)
        result = game_result(game, 3, 1)
        self.assertEqual((result.winner_id, result.loser_id), (self.a.pk, self.b.pk))
        self.assertFalse(result.overtime)
        self.assertFalse(result.shootout)

    def test_away_win(self):
        game = self._game(self.a, self.b)
        result = game_result(game, 1, 4)
        self.assertEqual(result.winner_id, self.b.pk)

    def test_tie_without_shootout_is_undecided(self):
        game = self._game(self.a, self.b)
        self.assertIsNone(game_result(game, 2, 2))
        self.assertIsNone(game_result(game, 0, 0))

    def test_tie_with_shootout_winner(self):
        game = self._game(self.a, self.b, shootout_winner_is_home=False)
        result = game_result(game, 2, 2)
        self.assertEqual(result.winner_id, self.b.pk)
        self.assertTrue(result.overtime)
        self.assertTrue(result.shootout)

    def test_overtime_flag(self):
        game = self._game(self.a, self.b, went_to_overtime=True)
        result = game_result(game, 3, 2)
        self.assertTrue(result.overtime)
        self.assertFalse(result.shootout)


class RecomputeTest(ResultsFixture):
    def test_stats_saved_rebuild_both_records(self):
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        self.assertEqual(self._record(self.a), (1, 0, 0, 0, 3, 1))
        self.assertEqual(self._record(self.b), (0, 0, 0, 1, 1, 3))

    def test_every_team_in_the_division_gets_a_row(self):
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        self.assertEqual(self._record(self.c), (0, 0, 0, 0, 0, 0))

    def test_overtime_win_counts_as_otw_and_otl(self):
        game = self._game(self.a, self.b, went_to_overtime=True)
        self._score(game, 2, 1)
        self.assertEqual(self._record(self.a)[:4], (0, 1, 0, 0))
        self.assertEqual(self._record(self.b)[:4], (0, 0, 1, 0))

    def test_shootout_counts_as_overtime(self):
        game = self._game(self.a, self.b, shootout_winner_is_home=False)
        self._score(game, 2, 2)
        self.assertEqual(self._record(self.a)[:4], (0, 0, 1, 0))
        self.assertEqual(self._record(self.b)[:4], (0, 1, 0, 0))

    def test_undecided_tie_counts_goals_but_no_result(self):
        game = self._game(self.a, self.b)
        self._score(game, 2, 2)
        self.assertEqual(self._record(self.a), (0, 0, 0, 0, 2, 2))

    def test_resaving_stats_never_double_counts(self):
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        for stat in Stat.objects.filter(matchup=game):
            stat.save()
        self._score(game, 3, 1)
        self.assertEqual(self._record(self.a), (1, 0, 0, 0, 3, 1))

    def test_deleting_stats_takes_the_game_out(self):
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        Stat.objects.filter(matchup=game).delete()
        self.assertEqual(self._record(self.a), (0, 0, 0, 0, 0, 0))

    def test_cancelled_game_is_left_out(self):
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        game.is_cancelled = True
        game.save()
        self.assertEqual(self._record(self.a), (0, 0, 0, 0, 0, 0))
        game.is_cancelled = False
        game.save()
        self.assertEqual(self._record(self.a), (1, 0, 0, 0, 3, 1))

    def test_cancelling_the_week_is_left_out(self):
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        self.week.is_cancelled = True
        self.week.save()
        self.assertEqual(self._record(self.a), (0, 0, 0, 0, 0, 0))

    def test_deleting_the_game_takes_it_out(self):
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        Stat.objects.filter(matchup=game).delete()
        game.delete()
        self.assertEqual(self._record(self.a), (0, 0, 0, 0, 0, 0))

    def test_postseason_game_is_left_out(self):
        game = self._game(self.a, self.b, is_postseason=True)
        self._score(game, 3, 1)
        self.assertEqual(self._record(self.a), (0, 0, 0, 0, 0, 0))

    def test_hand_kept_season_is_never_touched(self):
        self.season.standings_from_games = False
        self.season.save()
        Team_Stat.objects.create(
            team=self.a, season=self.season, division=self.division, win=7, loss=2
        )
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        row = Team_Stat.objects.get(team=self.a)
        self.assertEqual((row.win, row.loss), (7, 2))
        self.assertFalse(Team_Stat.objects.filter(team=self.b).exists())

    def test_duplicate_rows_are_collapsed(self):
        for _ in range(2):
            Team_Stat.objects.create(
                team=self.a, season=self.season, division=self.division, win=9
            )
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        self.assertEqual(Team_Stat.objects.filter(team=self.a).count(), 1)
        self.assertEqual(self._record(self.a)[0], 1)

    def test_deferred_recompute_runs_once_at_the_end(self):
        game = self._game(self.a, self.b)
        with standings_recompute_deferred():
            self._score(game, 3, 1)
            # Nothing rebuilt yet: the game save alone created zero rows.
            self.assertEqual(self._record(self.a)[0], 0)
        self.assertEqual(self._record(self.a)[0], 1)

    def test_recompute_ignores_unknown_pairs(self):
        recompute_team_stats(None, None)
        recompute_team_stats(self.season.pk, 9999)
        self.assertFalse(Team_Stat.objects.exists())

    def test_moving_a_game_to_another_division_refreshes_both(self):
        other_division = Division.objects.create(division=4)
        other_week = Week.objects.create(
            division=other_division, season=self.season, date=self.week.date
        )
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        game = MatchUp.objects.get(pk=game.pk)
        game.week = other_week
        game.save()
        self.assertEqual(self._record(self.a), (0, 0, 0, 0, 0, 0))
        moved = Team_Stat.objects.get(team=self.a, division=other_division)
        self.assertEqual(moved.win, 1)
