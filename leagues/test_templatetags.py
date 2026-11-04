"""Unit tests for leagues/templatetags/helpers.py — team_record."""

from django.test import SimpleTestCase

from leagues.templatetags.helpers import team_record


class TeamRecordTagTest(SimpleTestCase):
    """team_record is the single source of truth for record formatting."""

    def test_pre_2022_uses_win_loss_tie(self):
        self.assertEqual(team_record(2021, 3, 2, otw=1, otl=1, ties=1), "3-2-1")

    def test_2022_and_later_uses_standings_table_order(self):
        # W-OTW-L-OTL: the same left-to-right order as the standings table,
        # so "3-1-2-0" reads straight across the W / OTW / L / OTL columns.
        self.assertEqual(team_record(2022, 3, 2, otw=1, otl=0, ties=0), "3-1-2-0")

    def test_regulation_losses_come_before_overtime_losses(self):
        # Regression: the compact record used to be W-OTW-OTL-L while the
        # standings table was W-OTW-L-OTL, so a team with 3 regulation losses
        # read "0-1-0-3" on the schedule and "0 1 3 0" in the standings.
        self.assertEqual(team_record(2026, 0, 3, otw=1, otl=0), "0-1-3-0")
        self.assertEqual(team_record(2026, 0, 0, otw=0, otl=3), "0-0-0-3")

    def test_current_era_default_kwargs(self):
        self.assertEqual(team_record(2026, 5, 1), "5-0-1-0")

    def test_none_counts_render_as_zero(self):
        self.assertEqual(team_record(2026, None, None, otw=None, otl=None), "0-0-0-0")
        self.assertEqual(team_record(2021, None, None, ties=None), "0-0-0")

    def test_none_year_treated_as_current_era(self):
        self.assertEqual(team_record(None, 2, 1, otw=1, otl=0), "2-1-1-0")

    def test_year_accepts_string(self):
        self.assertEqual(team_record("2021", 1, 1, ties=2), "1-1-2")
