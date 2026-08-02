from collections import Counter

from django.db.models import Q, Sum
from django.views.generic import TemplateView

from leagues.models import MatchUp, Season, Stat, Team_Stat

from .schedule import add_goals_for_matchups

# Sections shown on the standings page. Each section shares one season
# dropdown because its divisions run on the same night and calendar.
SECTION_DIVISIONS = {
    "sunday": (1, 2),
    "wednesday": (3,),
    "monday": (4, 5),
}


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


def season_display_name(season):
    return "%s %s" % (season.get_season_type_display(), season.year)


def apply_tiebreakers(stats):
    """Order Team_Stat rows for one division by points, then the league
    tiebreakers: regulation wins → head-to-head → goal differential."""
    for ts in stats:
        ts.total_points = (ts.win * 3) + (ts.otw * 2) + ts.tie + ts.otl
        ts.regulation_wins = ts.win
        ts.total_wins = ts.win + ts.otw
        ts.gp = ts.win + ts.otw + ts.otl + ts.loss + ts.tie
        ts.goal_differential = ts.goals_for - ts.goals_against

    stats.sort(
        key=lambda ts: (
            -ts.total_points,
            -ts.regulation_wins,
            -ts.total_wins,
            -ts.tie,
            -ts.otl,
            -ts.goals_for,
            -ts.goals_against,
        )
    )

    for i in range(1, len(stats)):
        if stats[i].total_points == stats[i - 1].total_points:
            if stats[i].regulation_wins != stats[i - 1].regulation_wins:
                need_swap = stats[i].regulation_wins > stats[i - 1].regulation_wins
            elif check_teams_play(stats[i], stats[i - 1]):
                need_swap = check_h2h_record(stats[i], stats[i - 1])
            else:
                need_swap = check_goal_diff(stats[i], stats[i - 1])
            if need_swap:
                stats[i], stats[i - 1] = stats[i - 1], stats[i]

    return stats


def championship_results(pairs):
    """Winner of the championship game for each (division, season_id) pair.

    Returns {division int: Team}. A final that is unplayed or tied (no clear
    winner yet) produces no entry, so in-progress playoffs never show a
    premature champion.
    """
    if not pairs:
        return {}
    query = Q()
    for division, season_id in pairs:
        query |= Q(week__division__division=division, week__season_id=season_id)
    matchups = list(
        MatchUp.objects.filter(is_championship=True)
        .filter(query)
        .select_related("hometeam", "awayteam", "week__division")
        .order_by("week__date")
    )
    goals = {}
    for row in (
        Stat.objects.filter(matchup__in=matchups)
        .values("matchup_id", "team_id")
        .annotate(total=Sum("goals"))
    ):
        goals[(row["matchup_id"], row["team_id"])] = row["total"] or 0
    winners = {}
    for matchup in matchups:
        home = goals.get((matchup.id, matchup.hometeam_id), 0)
        away = goals.get((matchup.id, matchup.awayteam_id), 0)
        if home != away:
            winners[matchup.week.division.division] = (
                matchup.hometeam if home > away else matchup.awayteam
            )
    return winners


class TeamStatDetailView(TemplateView):
    template_name = "leagues/team_stat_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        seasons = {
            s.id: s for s in Season.objects.filter(team_stat__isnull=False).distinct()
        }

        def chronology(season_id):
            season = seasons[season_id]
            return (season.year, season.season_type or 0, season_id)

        # Seasons each division has stats for, newest first.
        division_seasons = {}
        for division, season_id in set(
            Team_Stat.objects.exclude(season__isnull=True).values_list(
                "division__division", "season_id"
            )
        ):
            division_seasons.setdefault(division, []).append(season_id)
        for season_ids in division_seasons.values():
            season_ids.sort(key=chronology, reverse=True)

        # One picker per section: which seasons it offers and which is chosen.
        selected = {}
        for section, divisions in SECTION_DIVISIONS.items():
            option_ids = sorted(
                {
                    sid
                    for division in divisions
                    for sid in division_seasons.get(division, [])
                },
                key=chronology,
                reverse=True,
            )
            raw = self.request.GET.get(section, "")
            selected_id = int(raw) if raw.isdigit() and int(raw) in seasons else None
            if selected_id not in option_ids:
                selected_id = None
            if selected_id is not None:
                selected[section] = selected_id

            # A "Current" choice only exists when the section's divisions are
            # in different seasons (e.g. one has started its next season and
            # the other hasn't). When they agree, "Current" would duplicate
            # the newest season option, so preselect that season instead.
            latest_ids = {
                division_seasons[division][0]
                for division in divisions
                if division_seasons.get(division)
            }
            diverged = len(latest_ids) > 1
            display_id = selected_id
            if display_id is None and not diverged and latest_ids:
                display_id = next(iter(latest_ids))

            context[f"{section}_seasons"] = self._labeled_options(
                option_ids, seasons, chronology
            )
            context[f"{section}_selected"] = display_id
            context[f"{section}_show_current"] = diverged
        context["picker_selected"] = selected

        displayed = {}  # division int -> season id shown

        def standings_for(section, division):
            season_id = selected.get(section)
            if season_id is None:
                latest = division_seasons.get(division, [])
                season_id = latest[0] if latest else None
            if season_id is None:
                return [], None
            displayed[division] = season_id
            stats = list(
                Team_Stat.objects.filter(
                    division__division=division, season_id=season_id
                ).select_related("team", "season")
            )
            return apply_tiebreakers(stats), season_display_name(seasons[season_id])

        def ranked(teams):
            for i, ts in enumerate(teams):
                ts.rank = i + 1
            return teams

        sunday_d1, sunday_d1_season = standings_for("sunday", 1)
        sunday_d2, sunday_d2_season = standings_for("sunday", 2)
        wednesday, wednesday_season = standings_for("wednesday", 3)
        monday_a, monday_a_season = standings_for("monday", 4)
        monday_b, monday_b_season = standings_for("monday", 5)

        champions = championship_results(list(displayed.items()))

        def champion_for(division, teams):
            # Attach the champion to the table it appears in — for Wednesday
            # this picks the champion's conference automatically.
            champ = champions.get(division)
            if champ and any(ts.team_id == champ.id for ts in teams):
                return champ
            return None

        wednesday_east = ranked([t for t in wednesday if t.team.conference == 1])
        wednesday_west = ranked([t for t in wednesday if t.team.conference == 2])
        context.update(
            {
                "sunday_d1": ranked(sunday_d1),
                "sunday_d2": ranked(sunday_d2),
                "wednesday_east": wednesday_east,
                "wednesday_west": wednesday_west,
                "monday_a": ranked(monday_a),
                "monday_b": ranked(monday_b),
                "sunday_d1_season": sunday_d1_season,
                "sunday_d2_season": sunday_d2_season,
                "wednesday_season": wednesday_season,
                "monday_a_season": monday_a_season,
                "monday_b_season": monday_b_season,
                "sunday_d1_champion": champion_for(1, sunday_d1),
                "sunday_d2_champion": champion_for(2, sunday_d2),
                "wednesday_east_champion": champion_for(3, wednesday_east),
                "wednesday_west_champion": champion_for(3, wednesday_west),
                "monday_a_champion": champion_for(4, monday_a),
                "monday_b_champion": champion_for(5, monday_b),
            }
        )
        return context

    @staticmethod
    def _labeled_options(option_ids, seasons, chronology):
        """Build dropdown options, numbering sessions when two seasons share a
        display name (e.g. two Monday sessions both labeled Spring 2025)."""
        names = Counter(season_display_name(seasons[sid]) for sid in option_ids)
        session = Counter()
        labels = {}
        for sid in sorted(option_ids, key=chronology):
            name = season_display_name(seasons[sid])
            if names[name] > 1:
                session[name] += 1
                labels[sid] = f"{name} (Session {session[name]})"
            else:
                labels[sid] = name
        return [{"id": sid, "label": labels[sid]} for sid in option_ids]
