import datetime
from datetime import timedelta
from collections import OrderedDict, namedtuple
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse

from django.views.generic.list import ListView
from django.db.models.functions import Lower, Coalesce
from django.db.models import Sum, Q, Max, Min, FloatField, Value
from django.db.models import F, When, IntegerField, Case, DecimalField, ExpressionWrapper, Func
from django.db import connection

from leagues.models import Season, Division, MatchUp, Stat, Roster, Player, Team, Team_Stat, Week, HomePage
import numpy as np
from dal import autocomplete
import os, requests
# Create your views here.

def home(request):
    # Filter matchups for the next 7 days
    today = datetime.date.today()
    next_week = today + datetime.timedelta(days=6)
    matchups = MatchUp.objects.filter(week__date__range=(today, next_week)).order_by('time')
    one_row = MatchUp.objects.filter(week__date__range=(today, next_week)).order_by('week__date').distinct('week__date')

    # Initialize weather data dictionary
    weather_data = {}

    # Fetch weather data for each unique game date in `one_row`
    api_key = os.environ.get("OPENWEATHERMAP_API_KEY")
    if not api_key:
        raise ValueError("The OpenWeatherMap API key is not set in the environment variables.")

    forecast_url = "https://api.openweathermap.org/data/2.5/forecast"
    current_weather_url = "https://api.openweathermap.org/data/2.5/weather"

    try:
        # Fetch 5-day forecast data
        forecast_params = {
            "q": "Alexandria,VA,US",
            "appid": api_key,
            "units": "imperial",  # Use Fahrenheit
        }
        forecast_response = requests.get(forecast_url, params=forecast_params)
        if forecast_response.status_code == 200:
            forecast = forecast_response.json()
            # Extract weather data for each game date
            for row in one_row:
                game_date = row.week.date.strftime("%Y-%m-%d")  # Ensure the date is in the correct format
                total_rain_mm = 0  # Initialize total rain for the day in mm
                weather_found = False

                for item in forecast["list"]:
                    if game_date in item["dt_txt"]:
                        # Add rain for the 3-hour period, if available
                        rain_mm = item.get("rain", {}).get("3h", 0)
                        total_rain_mm += rain_mm
                        # Store weather data for the first matching entry (e.g., temperature, wind, description)
                        if game_date not in weather_data:
                            weather_data[game_date] = {
                                "temp": item["main"].get("temp", "N/A"),
                                "wind_speed": item["wind"].get("speed", "N/A"),
                                "description": item["weather"][0].get("description", "N/A"),
                                "rain": total_rain_mm * 0.0393701,  # Convert rain to inches
                            }
                            weather_found = True
                            break

                # If no forecast data is found for today, fetch current weather
                if not weather_found and row.week.date == today:
                    current_params = {
                        "q": "Alexandria,VA,US",
                        "appid": api_key,
                        "units": "imperial",
                    }
                    current_response = requests.get(current_weather_url, params=current_params)
                    if current_response.status_code == 200:
                        current_weather = current_response.json()
                        weather_data[game_date] = {
                            "temp": current_weather["main"].get("temp", "N/A"),
                            "wind_speed": current_weather["wind"].get("speed", "N/A"),
                            "description": current_weather["weather"][0].get("description", "N/A"),
                            "rain": current_weather.get("rain", {}).get("1h", 0) * 0.0393701,  # Rain in inches
                        }

    except Exception as e:
        print(f"Error fetching weather data: {e}")

    # Add weather data and other context variables
    context = {
        "weather_data": weather_data,
        "season": Season.objects.all(),
        "matchup": matchups,
        "one_row": one_row,
        "homepage": HomePage.objects.last(),
    }
    return render(request, "core/home.html", context=context)

def leagues(request):
    return render(request, "leagues/index.html")

class MatchUpDetailView(ListView):
    context_object_name = 'matchup_list'

    def __init__(self):
        super(MatchUpDetailView, self).__init__()
        self._next_week = None

    def get_queryset(self):
        self._next_week = Week.objects.filter(date__gte=datetime.datetime.today()).order_by('date')
        if (self._next_week):
            self._next_week = self._next_week[0]
        else:
            #No upcoming matches so use most recent.
            self._next_week = Week.objects.latest('date')
        return MatchUp.objects.order_by('time').filter(week__date=self._next_week.date)

    def get_context_data(self, **kwargs):
        context = super(MatchUpDetailView, self).get_context_data(**kwargs)
        context['date_of_week'] = self.kwargs.get('date',self._next_week.date)
        matchups = MatchUp.objects.filter(week__date=context['date_of_week']).order_by('time')
        dmatchups = OrderedDict()
        for match in matchups:
            dmatchups[match.id] = {}
            dmatchups[match.id]['matchup'] = match
            dmatchups[match.id]['hometeamroster'] = Roster.objects.filter(team=match.hometeam).order_by('player_number', Lower('player__last_name'), Lower('player__first_name'))
            dmatchups[match.id]['awayteamroster'] = Roster.objects.filter(team=match.awayteam).order_by('player_number', Lower('player__last_name'), Lower('player__first_name'))

        context["matchups"] = dmatchups

        return context

class TeamStatDetailView(ListView):
    context_object_name = 'team_list'

    def get_queryset(self):
        # Need to get divisions seperately to account for d1 and d2 team having same number of points (could cause bug in h2h comparisson)
        team_stat_list = []
        d1_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=1).annotate(
                total_points = Coalesce((Sum('win') * 3) + (Sum('otw') * 2) + Sum('tie') + Sum('otl'),0),
                total_wins = Coalesce(Sum('win') + Sum('otw'),0)
                ).order_by('-total_points','-total_wins','-tie','-otl','-goals_for','-goals_against'))
        d2_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=2).annotate(
                total_points = Coalesce((Sum('win') * 3) + (Sum('otw') * 2) + Sum('tie') + Sum('otl'),0),
                total_wins = Coalesce(Sum('win') + Sum('otw'),0)
                ).order_by('-total_points','-total_wins','-tie','-otl','-goals_for','-goals_against'))
        draft_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=3).annotate(
                total_points =Coalesce((Sum('win') * 3) + (Sum('otw') * 2) + Sum('tie') + Sum('otl'),0),
                total_wins = Coalesce(Sum('win') + Sum('otw'),0)
                ).order_by('-total_points','-win','loss','-tie','-otl','-goals_for','-goals_against'))
        monday_a_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=4).annotate(
                total_points = Coalesce((Sum('win') * 3) + (Sum('otw') * 2) + Sum('tie') + Sum('otl'),0),
                total_wins = Coalesce(Sum('win') + Sum('otw'),0)
                ).order_by('-total_points','-total_wins','-tie','-otl','-goals_for','-goals_against'))
        monday_b_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=5).annotate(
                total_points = Coalesce((Sum('win') * 3) + (Sum('otw') * 2) + Sum('tie') + Sum('otl'),0),
                total_wins = Coalesce(Sum('win') + Sum('otw'),0)
                ).order_by('-total_points','-total_wins','-tie','-otl','-goals_for','-goals_against'))
        
        team_stat_list = d1_team_stat_list + d2_team_stat_list + draft_team_stat_list + monday_a_team_stat_list + monday_b_team_stat_list

        for i in range(len(team_stat_list)):
            if i > 0 and team_stat_list[i].total_points == team_stat_list[i-1].total_points:
                # print('points equal for index: {0}'.format(i))
                teams_played = check_teams_play(team_stat_list[i], team_stat_list[i-1])
                need_swap = False
                if teams_played: 
                    need_swap = check_h2h_record(team_stat_list[i], team_stat_list[i-1])
                if not teams_played and team_stat_list[i].total_wins == team_stat_list[i-1].total_wins: 
                    need_swap = check_goal_diff(team_stat_list[i], team_stat_list[i-1])
                if need_swap:
                    # print('swapping {0} and {1} at index {2}'.format(team_stat_list[i], team_stat_list[i-1], i))
                    team_stat_list[i], team_stat_list[i-1] = team_stat_list[i-1], team_stat_list[i]

        return ListAsQuerySet(team_stat_list, model=Team_Stat)

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
    # print('team1 :' + str(team1_goaldiff))
    # print('team2 :' + str(team2_goaldiff))
    if (team1_goaldiff) > (team2_goaldiff): return True
    return False

def check_teams_play(team1, team2):
    matchup = MatchUp.objects.filter(Q(awayteam=team1.team) | Q(hometeam=team1.team)).filter(
            Q(awayteam=team2.team) | Q(hometeam=team2.team)).exclude(is_postseason=True).values(
                'hometeam', 'awayteam', 'hometeam__team_name', 'awayteam__team_name')
    if matchup.exists():
        # print('team1: ' + str(team1.team.team_name) + ' plays ' + str(team2.team.team_name)) 
        return True
    return False

def check_h2h_record(team1, team2):
    matchup = MatchUp.objects.filter(Q(awayteam=team1.team) | Q(hometeam=team1.team)).filter(
        Q(awayteam=team2.team) | Q(hometeam=team2.team)).exclude(is_postseason=True).values(
            'hometeam', 'awayteam', 'hometeam__team_name', 'awayteam__team_name')
    matchup_details = add_goals_for_matchups(matchup)
    team1_win = 0
    team2_win = 0
    for match in matchup_details:
        if match['hometeam__team_name'] in str(team1.team):
            if match['home_goals'] > match['away_goals'] : team1_win += 1
        if match['awayteam__team_name'] in str(team1.team):
            if match['away_goals'] > match['home_goals']: team1_win += 1
        if match['hometeam__team_name'] in str(team2.team):
            if match['home_goals'] > match['away_goals'] : team2_win += 1
        if match['awayteam__team_name'] in str(team2.team):
            if match['away_goals'] > match['home_goals']: team2_win += 1
    # print(team1.team.team_name + ' wins:' + str(team1_win) + ' ' + team2.team.team_name + ' wins: ' + str(team2_win))
    if team1_win>team2_win: return True
    if team1_win == team2_win and team1_win != 0: return check_goal_diff(team1, team2)
    return False

class PlayerStatDetailView(ListView):
    context_object_name = 'player_stat_list'
    template_name = 'stat_list.html'

    def get_queryset(self):
        return Stat.objects.filter(team__season__is_current_season=True)

    def get_context_data(self, **kwargs):
        context = super(PlayerStatDetailView, self).get_context_data(**kwargs)
        season = self.kwargs.get('season', '0')
        context['seasons'] = Season.objects.order_by('-year', '-season_type')[:4]
        context['active_season'] = int(season)
        context['player_stat_list'] = OrderedDict()

        divisions = Division.objects.all()
        for div in divisions:
            players = Player.objects.filter(roster__team__division=div).select_related('roster__team')
            player_stats = get_player_stats(players, context['active_season']).filter(
                sum_games_played__gte=1).order_by(
                'rounded_average_goals_against', '-total_points', '-sum_goals', '-sum_assists'
            )
            context['player_stat_list'][str(div)] = player_stats
            # # Print only the desired values in descending order
            # for player in player_stats:
            #     print(f"{player['first_name']} {player['last_name']} - {player['rounded_average_goals_against']}")
                
        return context

def PlayerAllTimeStats_list(request):
    context = {}
    gender_filter = request.GET.get('gender', 'all')

    with connection.cursor() as cursor:
        if gender_filter == 'all':
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank, 
                       sub.id, sub.first_name, sub.last_name, sub.total_goals, 
                       sub.total_assists, sub.total_points 
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name, 
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists, 
                           (SUM(goals) + SUM(assists)) AS total_points 
                    FROM leagues_stat 
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id 
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name 
                    HAVING SUM(goals+assists) > 1 
                ) sub
                ORDER BY sub.total_points DESC 
                LIMIT 100;
            """
        elif gender_filter == 'F':
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank, 
                       sub.id, sub.first_name, sub.last_name, sub.total_goals, 
                       sub.total_assists, sub.total_points 
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name, 
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists, 
                           (SUM(goals) + SUM(assists)) AS total_points 
                    FROM leagues_stat 
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id 
                    WHERE leagues_player.gender = 'F'
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name 
                    HAVING SUM(goals+assists) > 1 
                ) sub
                ORDER BY sub.total_points DESC;
            """
        else:
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank, 
                       sub.id, sub.first_name, sub.last_name, sub.total_goals, 
                       sub.total_assists, sub.total_points 
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name, 
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists, 
                           (SUM(goals) + SUM(assists)) AS total_points 
                    FROM leagues_stat 
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id 
                    WHERE leagues_player.gender = %s
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name 
                    HAVING SUM(goals+assists) > 1 
                ) sub
                ORDER BY sub.total_points DESC 
                LIMIT 100;
            """
        if gender_filter in ['M', 'NB', 'NA']:
            cursor.execute(query, [gender_filter])
        else:
            cursor.execute(query)
        context["all_ranks"] = namedtuplefetchall(cursor)

    context["d1_ranks"] = get_division_ranks(1, gender_filter)
    context["d2_ranks"] = get_division_ranks(2, gender_filter)
    context["draft_ranks"] = get_division_ranks(3, gender_filter)
    context["mona_ranks"] = get_division_ranks(4, gender_filter)
    context["monb_ranks"] = get_division_ranks(5, gender_filter)
    context["selected_gender"] = gender_filter

    return render(request, "leagues/hof.html", context=context)

def get_division_ranks(division, gender_filter):
    with connection.cursor() as cursor:
        if gender_filter == 'all':
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank, 
                       sub.id, sub.first_name, sub.last_name, sub.total_goals, 
                       sub.total_assists, sub.total_points 
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name, 
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists, 
                           (SUM(goals) + SUM(assists)) AS total_points 
                    FROM leagues_stat 
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id 
                    JOIN leagues_team ON leagues_stat.team_id = leagues_team.id 
                    JOIN leagues_division ON leagues_team.division_id = leagues_division.id 
                    WHERE leagues_division.id = %s 
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name 
                    HAVING SUM(goals+assists) > 1 
                ) sub
                ORDER BY sub.total_points DESC 
                LIMIT 50;
            """
            cursor.execute(query, [division])
        elif gender_filter == 'F':
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank, 
                       sub.id, sub.first_name, sub.last_name, sub.total_goals, 
                       sub.total_assists, sub.total_points 
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name, 
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists, 
                           (SUM(goals) + SUM(assists)) AS total_points 
                    FROM leagues_stat 
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id 
                    JOIN leagues_team ON leagues_stat.team_id = leagues_team.id 
                    JOIN leagues_division ON leagues_team.division_id = leagues_division.id 
                    WHERE leagues_division.id = %s AND leagues_player.gender = 'F'
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name 
                    HAVING SUM(goals+assists) > 1 
                ) sub
                ORDER BY sub.total_points DESC;
            """
            cursor.execute(query, [division])
        else:
            query = """
                SELECT rank () OVER (ORDER BY total_points DESC) AS rank, 
                       sub.id, sub.first_name, sub.last_name, sub.total_goals, 
                       sub.total_assists, sub.total_points 
                FROM (
                    SELECT leagues_player.id, leagues_player.first_name, leagues_player.last_name, 
                           SUM(goals) AS total_goals, SUM(assists) AS total_assists, 
                           (SUM(goals) + SUM(assists)) AS total_points 
                    FROM leagues_stat 
                    JOIN leagues_player ON leagues_stat.player_id = leagues_player.id 
                    JOIN leagues_team ON leagues_stat.team_id = leagues_team.id 
                    JOIN leagues_division ON leagues_team.division_id = leagues_division.id 
                    WHERE leagues_division.id = %s AND leagues_player.gender = %s
                    GROUP BY leagues_player.id, leagues_player.first_name, leagues_player.last_name 
                    HAVING SUM(goals+assists) > 1 
                ) sub
                ORDER BY sub.total_points DESC 
                LIMIT 50;
            """
            cursor.execute(query, [division, gender_filter])
        return namedtuplefetchall(cursor)
    
def get_player_stats(players, season):
    stat_filters = Q(stat__isnull=True) | Q(stat__matchup__is_postseason=False) if season != 0 else Q(stat__team__is_active=True)
    
    return players.filter(
        stat_filters
    ).values(
        'id',
        'last_name',
        'first_name',
        'roster__team__team_name',
        'roster__team__id',
        'roster__position1',
        'roster__position2',
        'roster__is_captain',
    ).annotate(
        sum_goals=Sum(
            Case(
                When(stat__team=F('roster__team'), stat__team__season__id=season if season != 0 else F('roster__team__season__id'),
                     then=F('stat__goals')),
                default=0,
                output_field=IntegerField(),
            )
        ),
        sum_assists=Sum(
            Case(
                When(stat__team=F('roster__team'), stat__team__season__id=season if season != 0 else F('roster__team__season__id'),
                     then=F('stat__assists')),
                default=0,
                output_field=IntegerField(),
            )
        ),
        total_points=Sum(
            Case(
                When(stat__team=F('roster__team'), stat__team__season__id=season if season != 0 else F('roster__team__season__id'),
                     then=F('stat__assists') + F('stat__goals')),
                default=0,
                output_field=IntegerField(),
            )
        ),
        sum_goals_against=Sum(
            Case(
                When(stat__team=F('roster__team'), stat__team__season__id=season if season != 0 else F('roster__team__season__id'),
                     then=F('stat__goals_against') - F('stat__empty_net')),
                default=0,
                output_field=IntegerField(),
            )
        ),
        sum_games_played=Sum(
            Case(
                When(stat__team=F('roster__team'), stat__team__season__id=season if season != 0 else F('roster__team__season__id'),
                     then=1),
                default=0,
                output_field=IntegerField(),
            )
        ),
        average_goals_against=Case(
            When(sum_games_played=0, then=Value(0.0)),
            default=ExpressionWrapper(
                F('sum_goals_against') * 1.0 / F('sum_games_played'),
                output_field=FloatField()
            ),
            output_field=FloatField()
        )
    ).annotate(
        rounded_average_goals_against=Func(
            F('average_goals_against'),
            function='ROUND',
            template='%(function)s(%(expressions)s::numeric, 2)',
            output_field=DecimalField(max_digits=10, decimal_places=2)
        )
    )

def get_stats_for_matchup(match):
    return Stat.objects.filter(matchup=match).exclude(
            Q(goals=None) & Q(assists=None)).exclude(
            Q(goals=0) & Q(assists=0)).order_by(
            '-goals', '-assists')

def get_goalies_for_matchup(match, home):
    if home:
        return Stat.objects.filter(matchup=match).filter(
                (Q(goals=0) | Q(goals=None)) & (Q(
                assists=0) | Q(assists=None))& Q(
                matchup__hometeam=F('team')))
    else:
        return Stat.objects.filter(matchup=match).filter(
                (Q(goals=0) | Q(goals=None)) & (Q(
                assists=0) | Q(assists=None))& Q(
                matchup__awayteam=F('team')))

def add_goals_for_matchups(matchups):
    return matchups.annotate(home_goals=Sum(
                Case(
                    When(hometeam=F('stat__team'), then=F('stat__goals')),
                    default=0,
                    output_field=IntegerField(),
                    )
                ),
            away_goals=Sum(
                Case(
                    When(awayteam=F('stat__team'), then=F('stat__goals')),
                    default=0,
                    output_field=IntegerField(),
                    )
                )
            )

def get_matches_for_division(division):
    return MatchUp.objects.filter(
            hometeam__division=division).order_by(
            '-week__date').filter(awayteam__is_active=True)

def get_championships_for_division(division):
    return MatchUp.objects.filter(
            hometeam__division=division).order_by(
            '-week__date').filter(is_championship=True)

def get_matches_for_team(team):
    return MatchUp.objects.filter(
            (Q(hometeam__id=team) | Q(awayteam__id=team))).order_by(
            '-week__date')

def get_detailed_matchups(matchups):
    result = OrderedDict()
    for match in matchups.select_related('hometeam').select_related('awayteam').select_related('week').annotate(
            home_wins=Coalesce(Max('hometeam__team_stat__win'),0),
            home_losses=Coalesce(Max('hometeam__team_stat__loss'),0),
            home_ties=Coalesce(Max('hometeam__team_stat__tie'),0),
            home_otw=Coalesce(Max('hometeam__team_stat__otw'),0),
            home_otl=Coalesce(Max('hometeam__team_stat__otl'),0),
            away_wins=Coalesce(Max('awayteam__team_stat__win'),0),
            away_losses=Coalesce(Max('awayteam__team_stat__loss'),0),
            away_otw=Coalesce(Max('awayteam__team_stat__otw'),0),
            away_otl=Coalesce(Max('awayteam__team_stat__otl'),0),
            away_ties=Coalesce(Max('awayteam__team_stat__tie'),0)):
        if not result.get(str(match.week.date), False):
            result[str(match.week.date)] = OrderedDict()
        result[str(match.week.date)][str(match.id)] = {}
        result[str(match.week.date)][str(match.id)]['match'] = match
        relevant_stats = get_stats_for_matchup(match)
        home_goalie_stats = get_goalies_for_matchup(match, home=True)
        away_goalie_stats= get_goalies_for_matchup(match, home=False)
        result[str(match.week.date)][str(match.id)]['stats'] = relevant_stats
        result[str(match.week.date)][str(match.id)]['home_goalie_stats'] = home_goalie_stats
        result[str(match.week.date)][str(match.id)]['away_goalie_stats'] = away_goalie_stats
    return result

def get_schedule_for_matchups(matchups):
    schedule = OrderedDict()
    for match in matchups.annotate(
            home_wins=Coalesce(Max('hometeam__team_stat__win'),0),
            home_losses=Coalesce(Max('hometeam__team_stat__loss'),0),
            home_ties=Coalesce(Max('hometeam__team_stat__tie'),0),
            home_otw=Coalesce(Max('hometeam__team_stat__otw'),0),
            home_otl=Coalesce(Max('hometeam__team_stat__otl'),0),
            away_wins=Coalesce(Max('awayteam__team_stat__win'),0),
            away_losses=Coalesce(Max('awayteam__team_stat__loss'),0),
            away_otw=Coalesce(Max('awayteam__team_stat__otw'),0),
            away_otl=Coalesce(Max('awayteam__team_stat__otl'),0),
            away_ties=Coalesce(Max('awayteam__team_stat__tie'),0)):
        if not schedule.get(str(match.week.date), False):
            schedule[str(match.week.date)] = OrderedDict()
        if not schedule[str(match.week.date)].get(
                str(match.awayteam.division), False):
            schedule[str(match.week.date)][str(match.awayteam.division)] = []
        schedule[str(match.week.date)][str(match.awayteam.division)].append(match)
    return schedule

def schedule(request):
    context = {}
    context['view'] = "schedule"
    #Better to have a custom dictionary here than have 3 nested loops in the template
    matchups = MatchUp.objects.order_by('week__date', 'time').filter(
            awayteam__is_active=True).filter(
            week__date__gte=datetime.datetime.today())
    context['schedule'] = get_schedule_for_matchups(matchups)
    return render(request, "leagues/schedule.html", context=context)
 
def teams(request, team=0):
    context = {}
    team = int(team)
    context['view'] = "teams"
    context['schedule'] = OrderedDict()
    schedulematchups = MatchUp.objects.order_by('week__date', 'time').filter(
            awayteam__is_active=True).filter(Q(awayteam__id=team) | Q(hometeam__id=team)).filter(
            week__date__gte=datetime.datetime.today())
    context['schedule'] = get_schedule_for_matchups(schedulematchups)
    context['team'] = Team.objects.annotate(
            wins=Coalesce(Max('team_stat__win'),0),
            otw=Coalesce(Max('team_stat__otw'),0),
            otl=Coalesce(Max('team_stat__otl'),0),
            losses=Coalesce(Max('team_stat__loss'),0),
            ties=Coalesce(Max('team_stat__tie'),0)).get(id=team)
    scorematchups = get_matches_for_team(team).filter(
            week__date__lte=datetime.datetime.today())
    scorematchups = add_goals_for_matchups(scorematchups)
    context['matchups'] = get_detailed_matchups(scorematchups)
    context['roster'] = []
    players = Player.objects.filter(roster__team__id=team, roster__is_substitute=False)
    season = players.values_list('roster__team__season__id', flat=True).distinct()
    context['past_team_stats'] = get_stats_for_past_team(team)
    context['player_list'] = get_player_stats(players, int(season[0])).order_by(
            '-total_points', '-sum_goals', '-sum_assists', 'average_goals_against')
    for rosteritem in Roster.objects.select_related('team').select_related('player').filter(team__id=team, is_substitute=False):
        context['roster'].append({'player': rosteritem.player.first_name + " " + rosteritem.player.last_name,
            'position':[y for x,y in Roster.POSITION_TYPE if x == rosteritem.position1][0]})


    return render(request, "leagues/team.html", context=context)

def scores(request, division=1):
    context = {}
    context['view'] = "scores"
    context['divisions'] = Division.objects.all()
    context['matchups'] = OrderedDict()
    context['active_division'] = int(division)
    division = [i for i in Division.DIVISION_TYPE if context['active_division'] in i]
    #Check to see if the dvision from the URL is valid
    if len(division):
        #division ex: [(1, 'Sunday D1')]
        context['division_name'] = division[0][1]
        matchups = get_matches_for_division(context['active_division']).filter(
                week__date__lte=datetime.datetime.today())
        matchups = add_goals_for_matchups(matchups)
        context['matchups'] = get_detailed_matchups(matchups)
    return render(request, "leagues/scores.html", context=context)

def cups(request, division=1):
    context = {}
    context['view'] = "cups"
    context['divisions'] = Division.objects.all()
    context['matchups'] = OrderedDict()
    context['active_division'] = int(division)
    division = [i for i in Division.DIVISION_TYPE if context['active_division'] in i]
    #Check to see if the dvision from the URL is valid
    if len(division):
        #division ex: [(1, 'Sunday D1')]
        context['division_name'] = division[0][1]
        matchups = get_championships_for_division(context['active_division'])
        matchups = add_goals_for_matchups(matchups)
        context['matchups'] = get_detailed_matchups(matchups)
    return render(request, "leagues/cups.html", context=context)

def get_career_stats_for_player(player_id=0):

    if get_goalie_games_played(player_id) > 0: 
        return Stat.objects.filter(player_id=player_id).aggregate(
            career_goals=Sum('goals'), 
            career_assists=Sum('assists'),
            average_goals_per_season = ExpressionWrapper(
                Sum('goals')/get_seasons_played(player_id),
                output_field=DecimalField()),
            average_assists_per_season = ExpressionWrapper(
                Sum('assists')/get_seasons_played(player_id),
                output_field=DecimalField()),
            average_goals_against_per_game = ExpressionWrapper(
                Sum('goals_against')/get_goalie_games_played(player_id),
                output_field=DecimalField()),
            first_season=Min('team__season__year')
        )
    return Stat.objects.filter(player_id=player_id).aggregate(
            career_goals=Sum('goals'), 
            career_assists=Sum('assists'),
            first_season=Min('team__season__year'),
            average_goals_per_season = ExpressionWrapper(
                Sum('goals')/get_seasons_played(player_id),
                output_field=DecimalField()),
            average_assists_per_season = ExpressionWrapper(
                Sum('assists')/get_seasons_played(player_id),
                output_field=DecimalField())
    )

def get_goalie_games_played(player):
    games_played = Stat.objects.filter(player__id=player).filter((Q(goals=0) | Q(goals=None)) & (Q(assists=0) | Q(assists=None))).count()
    return float(games_played)

def get_seasons_played(player):
    count = Roster.objects.filter(player__id=player, is_substitute=False).count()
    return float(count)

def get_offensive_stats_for_player(player):
    return Stat.objects.filter(player_id=player).exclude((Q(goals=0) | Q(goals=None)) & (Q(assists=0) | Q(assists=None))).values(
        'team__id',
        'team__team_name',
        'team__team_stat__win',
        'team__team_stat__loss',
        'team__team_stat__tie',
        'team__season__year', 
        'team__season__season_type',
        'team__division').annotate(
            team_wins=Coalesce(Max('team__team_stat__win'),0),
            team_losses=Coalesce(Max('team__team_stat__loss'),0),
            team_otw=Coalesce(Max('team__team_stat__otw'),0),
            team_otl=Coalesce(Max('team__team_stat__otl'),0),
            sum_goals=Sum(
                Case(
                    When(team=F('team'), team__season__id=F('team__season__id'),
                            then=Coalesce('goals',0)),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            sum_assists=Sum(
                Case(
                    When(team=F('team'), team__season__id=F('team__season__id'),
                            then=Coalesce('assists',0)),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            total_points=Sum(
                Case(
                    When(team=F('team'), team__season__id=F('team__season__id'),
                            then=Coalesce('assists', 0)+Coalesce('goals',0)),
                    default=0,
                    output_field=IntegerField(),
                )
            )).order_by(
        '-team__season__year','-team__season__season_type')
        
def get_goalie_stats(player):

    return Stat.objects.filter(Q(player_id=player) & ((Q(goals=0) | Q(goals=None)) & (Q(
                assists=0) | Q(assists=None)))).values(
        'team__id',
        'team__team_name',
        'team__team_stat__tie',
        'team__season__year', 
        'team__season__season_type',
        'team__division').annotate(
        team_wins=Coalesce(Max('team__team_stat__win'),0),
        team_losses=Coalesce(Max('team__team_stat__loss'),0),
        team_otw=Coalesce(Max('team__team_stat__otw'),0),
        team_otl=Coalesce(Max('team__team_stat__otl'),0),
        sum_goals_against=Sum(
                Case(
                    When(team=F('team'), team__season__id=F('team__season__id'),
                            then=Coalesce('goals_against', 0)-Coalesce('empty_net', 0)),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            sum_games_played=Sum(
                Case(
                    When(team=F('team'), team__season__id=F('team__season__id'), then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            average_goals_against=Sum(
                Case(
                    When(team=F('team'), team__season__id=F('team__season__id'),
                            then=Coalesce('goals_against', 0.0)-Coalesce('empty_net', 0.0)),
                    default=0.0,
                    output_field=DecimalField(),
                )
            )/Sum(
                Case(
                    When(team=F('team'), team__season__id=F('team__season__id'), then=1.0),
                    default=0.0001,
                    output_field=DecimalField(),
                )
            )).order_by(
        '-team__season__year','-team__season__season_type')

def get_stats_for_past_team(team):
    team_name = Team.objects.filter(id=team).values_list('team_name', flat=True)
    return Team_Stat.objects.filter(team__team_name__in=team_name).values(
        'team__id',
        'team__team_name',
        'win',
        'otw',
        'otl',
        'loss',
        'tie',
        'goals_for',
        'goals_against',
        'team__season__year', 
        'team__season__season_type',
        'team__division').order_by(
        '-team__season__year','-team__season__season_type')
   
def namedtuplefetchall(cursor):
    # """
    # Return all rows from a cursor as a namedtuple.
    # Assume the column names are unique.
    # """
    desc = cursor.description
    nt_result = namedtuple("Result", [col[0] for col in desc])
    return [nt_result(*row) for row in cursor.fetchall()]

class PlayerAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Player.objects.none()

        qs = Player.objects.all()

        if self.q:
            qs = qs.filter(Q(first_name__icontains=self.q) | Q(last_name__icontains=self.q))

        return qs

def calculate_player_stats(player, season_mapping):
    offensive_stats = Stat.objects.filter(player=player).select_related('team__season', 'team__division').values(
        'team__season__year', 'team__season__season_type', 'team__team_name', 'team__division', 'team__id'
    ).annotate(
        sum_goals=Sum('goals'),
        sum_assists=Sum('assists'),
        team_wins=Max('team__team_stat__win'),
        team_losses=Max('team__team_stat__loss'),
        team_ties=Max('team__team_stat__tie'),
        team_otw=Max('team__team_stat__otw'),
        team_otl=Max('team__team_stat__otl')
    ).order_by('team__season__year', 'team__season__season_type')  # Earliest to most recent for trend chart

    # Filter out seasons where both goals and assists are zero
    offensive_stats = [stat for stat in offensive_stats if (stat['sum_goals'] or 0) > 0 or (stat['sum_assists'] or 0) > 0]

    # Create a separate list for the table with most recent seasons on top
    offensive_stats_table = list(offensive_stats)[::-1]

    player_seasons = [f"{stat['team__season__year']} {season_mapping.get(stat['team__season__season_type'], 'Unknown')} ({stat['team__team_name']})" for stat in offensive_stats]
    player_goals = [stat['sum_goals'] if stat['sum_goals'] is not None else 0 for stat in offensive_stats]
    player_assists = [stat['sum_assists'] if stat['sum_assists'] is not None else 0 for stat in offensive_stats]
    player_points = [goals + assists for goals, assists in zip(player_goals, player_assists)]

    # Calculate trend line for total points
    if player_points:
        x = np.arange(len(player_points))
        y = np.array(player_points)
        if len(x) > 1:  # Ensure there are enough points to calculate a trend line
            trend = np.polyfit(x, y, 1)
            trend_line = trend[0] * x + trend[1]
        else:
            trend_line = y  # Not enough points to calculate a trend line
        trend_line = trend_line.tolist()  # Convert numpy array to list for JSON serialization
    else:
        trend_line = []

    return {
        'offensive_stats': offensive_stats_table,  # Most recent to earliest for table
        'player_seasons': player_seasons,
        'player_goals': player_goals,
        'player_assists': player_assists,
        'player_points': player_points,
        'trend_line': trend_line
    }

def player_view(request, player_id):
    player = get_object_or_404(Player, id=player_id)
    season_mapping = {
        1: 'Spring',
        2: 'Summer',
        3: 'Fall',
        4: 'Winter'
    }
    stats = calculate_player_stats(player, season_mapping)

    context = {
        'view': 'player',
        'player': player,
        'career_stats': get_career_stats_for_player(player_id),
        'seasons': get_seasons_played(player_id),
        'goalie_stats': get_goalie_stats(player_id),
        **stats,
        # Add other context variables as needed
    }

    return render(request, 'leagues/player.html', context)
def player_trends_view(request):
    player_id = request.GET.get('player_id')
    timespan = request.GET.get('timespan', request.session.get('timespan', 'all'))  # Default to all seasons if not provided
    division = request.GET.get('division', 'all')  # Default to all divisions
    context = {'view': 'player_trends'}

    # Store the timespan in the session
    request.session['timespan'] = timespan

    all_players = Player.objects.all()
    context['all_players'] = all_players

    divisions = Division.DIVISION_TYPE
    context['divisions'] = divisions

    if player_id:
        try:
            player = get_object_or_404(Player, id=player_id)
            season_mapping = {
                1: 'Spring',
                2: 'Summer',
                3: 'Fall',
                4: 'Winter'
            }
            stats = calculate_player_stats(player, season_mapping)

            # Apply division and timespan filters if necessary
            offensive_stats = Stat.objects.filter(player=player).select_related('team__season', 'team__division').values(
                'team__season__year', 'team__season__season_type', 'team__team_name', 'team__division', 'team__id'
            ).annotate(
                sum_goals=Sum('goals'),
                sum_assists=Sum('assists')
            ).order_by('-team__season__year', '-team__season__season_type')
            
            if division != 'all':
                offensive_stats = offensive_stats.filter(team__division=division)
            
            if timespan != 'all':
                timespan = int(timespan)
                offensive_stats = offensive_stats[:timespan]
            
            # Reverse the order to display the most recent seasons on the far right
            offensive_stats = list(offensive_stats)[::-1]
            
            # Check the player's position for each season and filter out seasons with zero goals and zero assists if the player's primary position is not goalie or defense
            filtered_stats = []
            for stat in offensive_stats:
                roster_entry = Roster.objects.filter(player=player, is_substitute=False, team_id=stat['team__id']).first()
                primary_position = roster_entry.position1 if roster_entry else None
                sum_goals = stat['sum_goals'] if stat['sum_goals'] is not None else 0
                sum_assists = stat['sum_assists'] if stat['sum_assists'] is not None else 0
                if primary_position not in [3, 4]:  # 3: Defense, 4: Goalie
                    if sum_goals > 0 or sum_assists > 0:
                        filtered_stats.append(stat)
                else:
                    filtered_stats.append(stat)
            
            player_seasons = [f"{stat['team__season__year']} {season_mapping.get(stat['team__season__season_type'], 'Unknown')} ({stat['team__team_name']})" for stat in filtered_stats]
            player_goals = [stat['sum_goals'] if stat['sum_goals'] is not None else 0 for stat in filtered_stats]
            player_assists = [stat['sum_assists'] if stat['sum_assists'] is not None else 0 for stat in filtered_stats]
            player_points = [goals + assists for goals, assists in zip(player_goals, player_assists)]

            average_goals = sum(player_goals) / len(player_goals) if player_goals else 0
            average_assists = sum(player_assists) / len(player_assists) if player_assists else 0
            average_points = sum(player_points) / len(player_points) if player_points else 0

            # Calculate trend line for total points
            x = np.arange(len(player_points))
            y = np.array(player_points)
            if len(x) > 1:  # Ensure there are enough points to calculate a trend line
                trend = np.polyfit(x, y, 1)
                trend_line = trend[0] * x + trend[1]
            else:
                trend_line = y  # Not enough points to calculate a trend line

            context.update({
                'player': player,
                'player_seasons': player_seasons,
                'player_goals': player_goals,
                'player_assists': player_assists,
                'player_points': player_points,
                'trend_line': trend_line.tolist(),  # Convert numpy array to list for JSON serialization
                'timespan': timespan,
                'player_id': player_id,
                'division': division,
                'average_goals': average_goals,
                'average_assists': average_assists,
                'average_points': average_points,
            })

            # Debug statements
            print(f"Player: {player.first_name} {player.last_name}")
            print(f"Seasons: {player_seasons}")
            print(f"Goals: {player_goals}")
            print(f"Assists: {player_assists}")
            print(f"Points: {player_points}")
            print(f"Average Goals: {average_goals}")
            print(f"Average Assists: {average_assists}")
            print(f"Average Points: {average_points}")
            print(f"Trend Line: {trend_line}")

        except Exception as e:
            print(f"Error: {e}")

    return render(request, 'leagues/player_trends.html', context=context)
