from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.views.generic.list import ListView

from leagues.models import MatchUp, Team_Stat

from .schedule import add_goals_for_matchups


class ListAsQuerySet(list):
    def __init__(self, *args, model, **kwargs):
        self.model = model
        super().__init__(*args, **kwargs)

    def filter(self, *args, **kwargs):
        return self  # filter ignoring, but you can impl custom filter

    def order_by(self, *args, **kwargs):
        return self


def check_goal_diff(team1, team2):
    team1_goaldiff = team1.goals_for - team1.goals_against
    team2_goaldiff = team2.goals_for - team2.goals_against
    if (team1_goaldiff) > (team2_goaldiff):
        return True
    return False


def check_teams_play(team1, team2):
    matchup = (
        MatchUp.objects.filter(Q(awayteam=team1.team) | Q(hometeam=team1.team))
        .filter(Q(awayteam=team2.team) | Q(hometeam=team2.team))
        .exclude(is_postseason=True)
        .values("hometeam", "awayteam", "hometeam__team_name", "awayteam__team_name")
    )
    if matchup.exists():
        return True
    return False


def check_h2h_record(team1, team2):
    matchup = (
        MatchUp.objects.filter(Q(awayteam=team1.team) | Q(hometeam=team1.team))
        .filter(Q(awayteam=team2.team) | Q(hometeam=team2.team))
        .exclude(is_postseason=True)
        .values("hometeam", "awayteam", "hometeam__team_name", "awayteam__team_name")
    )
    matchup_details = add_goals_for_matchups(matchup)
    team1_win = 0
    team2_win = 0
    for match in matchup_details:
        if match["hometeam__team_name"] in str(team1.team):
            if match["home_goals"] > match["away_goals"]:
                team1_win += 1
        if match["awayteam__team_name"] in str(team1.team):
            if match["away_goals"] > match["home_goals"]:
                team1_win += 1
        if match["hometeam__team_name"] in str(team2.team):
            if match["home_goals"] > match["away_goals"]:
                team2_win += 1
        if match["awayteam__team_name"] in str(team2.team):
            if match["away_goals"] > match["home_goals"]:
                team2_win += 1
    if team1_win > team2_win:
        return True
    if team1_win == team2_win and team1_win != 0:
        return check_goal_diff(team1, team2)
    return False


class TeamStatDetailView(ListView):
    context_object_name = "team_list"

    def get_queryset(self):
        # Need to get divisions separately to account for d1 and d2 team having
        # same number of points (could cause bug in h2h comparison)
        # Note: Season filtering temporarily disabled - shows all seasons aggregated

        team_stat_list = []
        d1_team_stat_list = list(
            Team_Stat.objects.filter(team__is_active=True)
            .filter(division=1)
            .select_related("team")
            .annotate(
                total_points=Coalesce(
                    (Sum("win") * 3) + (Sum("otw") * 2) + Sum("tie") + Sum("otl"), 0
                ),
                total_wins=Coalesce(Sum("win") + Sum("otw"), 0),
                regulation_wins=Coalesce(Sum("win"), 0),  # Add regulation wins
            )
            .order_by(
                "-total_points",
                "-regulation_wins",
                "-total_wins",
                "-tie",
                "-otl",
                "-goals_for",
                "-goals_against",
            )
        )
        d2_team_stat_list = list(
            Team_Stat.objects.filter(team__is_active=True)
            .filter(division=2)
            .select_related("team")
            .annotate(
                total_points=Coalesce(
                    (Sum("win") * 3) + (Sum("otw") * 2) + Sum("tie") + Sum("otl"), 0
                ),
                total_wins=Coalesce(Sum("win") + Sum("otw"), 0),
                regulation_wins=Coalesce(Sum("win"), 0),  # Add regulation wins
            )
            .order_by(
                "-total_points",
                "-regulation_wins",
                "-total_wins",
                "-tie",
                "-otl",
                "-goals_for",
                "-goals_against",
            )
        )
        draft_team_stat_list = list(
            Team_Stat.objects.filter(team__is_active=True)
            .filter(division=3)
            .select_related("team")
            .annotate(
                total_points=Coalesce(
                    (Sum("win") * 3) + (Sum("otw") * 2) + Sum("tie") + Sum("otl"), 0
                ),
                total_wins=Coalesce(Sum("win") + Sum("otw"), 0),
                regulation_wins=Coalesce(Sum("win"), 0),  # Add regulation wins
            )
            .order_by(
                "-total_points",
                "-regulation_wins",
                "-win",
                "loss",
                "-tie",
                "-otl",
                "-goals_for",
                "-goals_against",
            )
        )
        monday_a_team_stat_list = list(
            Team_Stat.objects.filter(team__is_active=True)
            .filter(division=4)
            .select_related("team")
            .annotate(
                total_points=Coalesce(
                    (Sum("win") * 3) + (Sum("otw") * 2) + Sum("tie") + Sum("otl"), 0
                ),
                total_wins=Coalesce(Sum("win") + Sum("otw"), 0),
                regulation_wins=Coalesce(Sum("win"), 0),  # Add regulation wins
            )
            .order_by(
                "-total_points",
                "-regulation_wins",
                "-total_wins",
                "-tie",
                "-otl",
                "-goals_for",
                "-goals_against",
            )
        )
        monday_b_team_stat_list = list(
            Team_Stat.objects.filter(team__is_active=True)
            .filter(division=5)
            .select_related("team")
            .annotate(
                total_points=Coalesce(
                    (Sum("win") * 3) + (Sum("otw") * 2) + Sum("tie") + Sum("otl"), 0
                ),
                total_wins=Coalesce(Sum("win") + Sum("otw"), 0),
                regulation_wins=Coalesce(Sum("win"), 0),  # Add regulation wins
            )
            .order_by(
                "-total_points",
                "-regulation_wins",
                "-total_wins",
                "-tie",
                "-otl",
                "-goals_for",
                "-goals_against",
            )
        )

        team_stat_list = (
            d1_team_stat_list
            + d2_team_stat_list
            + draft_team_stat_list
            + monday_a_team_stat_list
            + monday_b_team_stat_list
        )

        for i in range(len(team_stat_list)):
            if (
                i > 0
                and team_stat_list[i].total_points == team_stat_list[i - 1].total_points
            ):
                need_swap = False

                # First tiebreaker: Regulation wins
                if (
                    team_stat_list[i].regulation_wins
                    != team_stat_list[i - 1].regulation_wins
                ):
                    # Team with more regulation wins should be higher
                    need_swap = (
                        team_stat_list[i].regulation_wins
                        > team_stat_list[i - 1].regulation_wins
                    )
                else:
                    # Second tiebreaker: Head-to-head (if teams have played)
                    teams_played = check_teams_play(
                        team_stat_list[i], team_stat_list[i - 1]
                    )
                    if teams_played:
                        need_swap = check_h2h_record(
                            team_stat_list[i], team_stat_list[i - 1]
                        )
                    else:
                        # Third tiebreaker: Goal differential (if no H2H or tied reg wins)
                        need_swap = check_goal_diff(
                            team_stat_list[i], team_stat_list[i - 1]
                        )

                if need_swap:
                    team_stat_list[i], team_stat_list[i - 1] = (
                        team_stat_list[i - 1],
                        team_stat_list[i],
                    )

        return ListAsQuerySet(team_stat_list, model=Team_Stat)
