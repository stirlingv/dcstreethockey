"""
Tests for leagues/results.py and leagues/signals.py: a game's result from
its score, and the standings rebuilt from every game in a season.
"""

import datetime

from django.db.models import Sum
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
    tally_records,
)
from leagues import standings_switch


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

    def test_shootout_goal_counts_for_the_team_but_no_player(self):
        # The final score of a shootout game gives the winner one more goal.
        # It belongs to the team, never to a player.
        game = self._game(self.a, self.b, shootout_winner_is_home=False)
        self._score(game, 2, 2)
        self.assertEqual(self._record(self.b)[4:], (3, 2))
        self.assertEqual(self._record(self.a)[4:], (2, 3))
        self.assertEqual(
            Stat.objects.filter(matchup=game).aggregate(total=Sum("goals"))["total"],
            4,
        )

    def test_playoff_shootout_is_a_result_but_not_a_standings_game(self):
        game = self._game(
            self.a, self.b, is_postseason=True, shootout_winner_is_home=True
        )
        self._score(game, 1, 1)
        self.assertTrue(game_result(game, 1, 1).shootout)
        self.assertEqual(self._record(self.a), (0, 0, 0, 0, 0, 0))

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

    def test_tally_records_reads_without_writing(self):
        self.season.standings_from_games = False
        self.season.save()
        game = self._game(self.a, self.b)
        self._score(game, 3, 1)
        tally, undecided = tally_records(self.season.pk, self.division.pk)
        self.assertEqual(
            tally[self.a.pk],
            {
                "win": 1,
                "otw": 0,
                "loss": 0,
                "otl": 0,
                "goals_for": 3,
                "goals_against": 1,
            },
        )
        self.assertEqual(tally[self.c.pk]["win"], 0)
        self.assertEqual(undecided, [])
        self.assertFalse(Team_Stat.objects.exists())

    def test_tally_records_names_the_tied_games_with_their_score(self):
        tied = self._game(self.a, self.b)
        self._score(tied, 2, 2)
        self._game(self.a, self.c)  # unplayed: nothing to decide yet
        tally, undecided = tally_records(self.season.pk, self.division.pk)
        self.assertEqual([g.pk for g in undecided], [tied.pk])
        self.assertEqual((undecided[0].home_goals, undecided[0].away_goals), (2, 2))
        self.assertEqual(tally[self.a.pk]["goals_for"], 2)

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


class StandingsSwitchTest(ResultsFixture):
    """leagues/standings_switch.py: a hand-kept season's typed-in records
    next to what its games say, and the switch to computed standings."""

    def setUp(self):
        super().setUp()
        self.season.standings_from_games = False
        self.season.save()
        # Alpha beat Bravo 3-1 in regulation; Bravo beat Alpha 3-2 in
        # overtime, before the "went to OT" box existed, so the game carries
        # no overtime mark but the typed-in records count it as one.
        self.regulation = self._game(self.a, self.b)
        self._score(self.regulation, 3, 1)
        self.overtime = self._game(
            self.a,
            self.b,
            week=Week.objects.create(
                division=self.division,
                season=self.season,
                date=datetime.date(2027, 3, 8),
            ),
        )
        self._score(self.overtime, 2, 3)
        self._typed(self.a, win=1, otl=1)
        self._typed(self.b, otw=1, loss=1)

    def _typed(self, team, **record):
        row, _ = Team_Stat.objects.get_or_create(
            team=team, season=self.season, division=self.division
        )
        for field, value in record.items():
            setattr(row, field, value)
        row.save()
        return row

    def _rows(self):
        (division,) = standings_switch.preview(self.season)
        return division, {row["team"].pk: row for row in division["rows"]}

    def test_preview_shows_typed_next_to_computed(self):
        division, rows = self._rows()
        self.assertEqual(division["division"], self.division)
        alpha = rows[self.a.pk]
        self.assertEqual(alpha["typed_record"], "1-0-0-1")
        self.assertEqual(alpha["computed_record"], "1-0-1-0")
        self.assertEqual((alpha["typed_points"], alpha["computed_points"]), (4, 3))
        self.assertEqual((alpha["typed_gp"], alpha["computed_gp"]), (2, 2))
        self.assertTrue(alpha["changed"])
        # Charlie has no typed row and no games: nothing to change.
        charlie = rows[self.c.pk]
        self.assertEqual(charlie["typed_record"], "0-0-0-0")
        self.assertFalse(charlie["changed"])
        self.assertEqual(division["changed"], 2)

    def test_preview_counts_unmarked_overtime_games_and_names_candidates(self):
        division, rows = self._rows()
        self.assertEqual(rows[self.a.pk]["ot_to_mark"], 1)
        self.assertEqual(rows[self.b.pk]["ot_to_mark"], 1)
        self.assertEqual(division["ot_to_mark"], 2)
        # Only the one-goal game is a candidate; the 3-1 game is not.
        candidates = rows[self.a.pk]["candidates"]
        self.assertEqual([g.pk for g in candidates], [self.overtime.pk])
        self.assertEqual((candidates[0].home_goals, candidates[0].away_goals), (2, 3))
        self.assertIn(
            f"/admin/leagues/matchup/{self.overtime.pk}/change/",
            candidates[0].admin_url,
        )

    def test_marking_the_overtime_game_clears_the_warning(self):
        self.overtime.went_to_overtime = True
        self.overtime.save()
        division, rows = self._rows()
        self.assertEqual(division["ot_to_mark"], 0)
        self.assertEqual(division["changed"], 0)
        self.assertEqual(rows[self.a.pk]["computed_record"], "1-0-0-1")
        self.assertEqual(rows[self.a.pk]["candidates"], [])

    def test_shootout_games_already_count_as_overtime(self):
        self.overtime.shootout_winner_is_home = False
        self.overtime.save()
        self._score(self.overtime, 2, 2)
        division, rows = self._rows()
        self.assertEqual(division["ot_to_mark"], 0)
        self.assertEqual(rows[self.b.pk]["computed_record"], "0-1-1-0")

    def test_preview_lists_tied_games_without_a_shootout_winner(self):
        self._score(self.overtime, 2, 2)
        division, rows = self._rows()
        self.assertEqual([g.pk for g in division["undecided"]], [self.overtime.pk])
        self.assertIn("/change/", division["undecided"][0].admin_url)
        self.assertEqual(rows[self.a.pk]["computed_gp"], 1)

    def test_preview_rows_are_ordered_by_computed_points(self):
        division, _ = self._rows()
        names = [row["team"].team_name for row in division["rows"]]
        self.assertEqual(names, ["Alpha", "Bravo", "Charlie"])

    def test_preview_covers_every_division_the_season_plays_in(self):
        other = Division.objects.create(division=4)
        Week.objects.create(
            division=other, season=self.season, date=datetime.date(2027, 3, 2)
        )
        divisions = [
            d["division"].division for d in standings_switch.preview(self.season)
        ]
        self.assertEqual(divisions, [4, 5])

    def test_switch_flips_the_season_and_rebuilds_the_records(self):
        self.overtime.went_to_overtime = True
        self.overtime.save()
        # A typing slip: Bravo's loss was never recorded.
        self._typed(self.b, otw=1, loss=0)
        divisions = standings_switch.switch(self.season)
        self.assertEqual([d.pk for d in divisions], [self.division.pk])
        self.assertTrue(Season.objects.get(pk=self.season.pk).standings_from_games)
        self.assertEqual(self._record(self.a), (1, 0, 1, 0, 5, 4))
        self.assertEqual(self._record(self.b), (0, 1, 0, 1, 4, 5))
        self.assertEqual(self._record(self.c), (0, 0, 0, 0, 0, 0))

    def test_after_the_switch_saving_stats_updates_the_record_by_itself(self):
        standings_switch.switch(self.season)
        self._score(self.regulation, 1, 3)
        # _record is (win, otw, otl, loss, ...): two regulation losses.
        self.assertEqual(self._record(self.a)[:4], (0, 0, 0, 2))

    def test_switch_is_idempotent(self):
        standings_switch.switch(self.season)
        before = self._record(self.a)
        standings_switch.switch(self.season)
        self.assertEqual(self._record(self.a), before)

    def test_mark_overtime_ticks_the_chosen_games(self):
        marked = standings_switch.mark_overtime(
            self.season, [str(self.overtime.pk), "junk", ""]
        )
        self.assertEqual(marked, 1)
        self.assertTrue(MatchUp.objects.get(pk=self.overtime.pk).went_to_overtime)
        self.assertFalse(MatchUp.objects.get(pk=self.regulation.pk).went_to_overtime)
        division, rows = self._rows()
        self.assertEqual(division["ot_to_mark"], 0)

    def test_mark_overtime_ignores_games_from_other_seasons(self):
        other_season = Season.objects.create(year=2027, season_type=2)
        other_week = Week.objects.create(
            division=self.division, season=other_season, date=datetime.date(2027, 6, 1)
        )
        stranger = self._game(self.a, self.b, week=other_week)
        self.assertEqual(standings_switch.mark_overtime(self.season, [stranger.pk]), 0)
        self.assertFalse(MatchUp.objects.get(pk=stranger.pk).went_to_overtime)

    def test_mark_overtime_with_nothing_ticked_changes_nothing(self):
        self.assertEqual(standings_switch.mark_overtime(self.season, []), 0)
