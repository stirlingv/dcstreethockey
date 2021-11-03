import datetime
from datetime import timedelta
from collections import OrderedDict
import decimal

from django.shortcuts import render
from django.views.generic.list import ListView
from django.db.models.functions import Lower, Coalesce
from django.db.models import Sum, Q, Max, Exists, Value, Count
from django.db.models import F, When, IntegerField, Case, DecimalField, ExpressionWrapper

from leagues.models import Season
from leagues.models import Division
from leagues.models import MatchUp
from leagues.models import Stat
from leagues.models import Roster
from leagues.models import Player
from leagues.models import Team
from leagues.models import Team_Stat
from leagues.models import Week
from leagues.models import HomePage
# Create your views here.

def home(request):
    context = {}
    # context["season"] = Season.objects.get(is_current_season=1)
    context["season"] = Season.objects.all()
    context["matchup"]  = MatchUp.objects.order_by('time').filter(week__date__range=(datetime.date.today(), datetime.date.today() + timedelta(days=6)))
    context["one_row"]  = MatchUp.objects.filter(week__date__range=(datetime.date.today(), datetime.date.today() + timedelta(days=6))).order_by('week__date').distinct('week__date')
    context["homepage"] = HomePage.objects.last()
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
        if self._next_week:
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
            dmatchups[match.id]['hometeamroster'] = Roster.objects.filter(team=match.hometeam).order_by(Lower('player__last_name'), Lower('player__first_name'))
            dmatchups[match.id]['awayteamroster'] = Roster.objects.filter(team=match.awayteam).order_by(Lower('player__last_name'), Lower('player__first_name'))

        context["matchups"] = dmatchups

        return context

class TeamStatDetailView(ListView):
    context_object_name = 'team_list'

    def get_queryset(self):
        # Need to get divisions seperately to account for d1 and d2 team having same number of points (could cause bug in h2h comparisson)
        team_stat_list = [] 
        d1_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=1).annotate(
                total_points = Coalesce((Sum('win') * 2) + Sum('tie') + Sum('otl'),0)
                ).order_by('-total_points','-win','loss','-tie','-otl','-goals_for','-goals_against'))
        d2_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=2).annotate(
                total_points = Coalesce((Sum('win') * 2) + Sum('tie') + Sum('otl'),0)
                ).order_by('-total_points','-win','loss','-tie','-otl','-goals_for','-goals_against'))
        draft_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=3).annotate(
                total_points = Coalesce((Sum('win') * 2) + Sum('tie') + Sum('otl'),0)
                ).order_by('-total_points','-win','loss','-tie','-otl','-goals_for','-goals_against'))
        coed_team_stat_list = list(Team_Stat.objects.filter(
                team__is_active=True).filter(division=4).annotate(
                total_points = Coalesce((Sum('win') * 2) + Sum('tie') + Sum('otl'),0)
                ).order_by('-total_points','-win','loss','-tie','-otl','-goals_for','-goals_against'))
        
        team_stat_list = d1_team_stat_list + d2_team_stat_list + draft_team_stat_list + coed_team_stat_list

        for i in range(len(team_stat_list)):
            if i > 0 and team_stat_list[i].total_points == team_stat_list[i-1].total_points: 
                # print('points equal for index: {0}'.format(i))
                need_swap = check_h2h_record(team_stat_list[i], team_stat_list[i-1])
                if need_swap:
                    # print('swapping {0} and {1} at imdex {2}'.format(team_stat_list[i], team_stat_list[i-1], i))
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

def check_h2h_record(team1, team2):
    matchup = MatchUp.objects.filter(Q(awayteam=team1.team) | Q(hometeam=team1.team)).filter(
        Q(awayteam=team2.team) | Q(hometeam=team2.team)).exclude(is_postseason=True).values(
            'hometeam', 'awayteam', 'hometeam__team_name', 'awayteam__team_name')
    matchup_details = add_goals_for_matchups(matchup)
    for match in matchup_details:
        if match['hometeam__team_name'] in str(team1.team):
            if match['home_goals'] > match['away_goals']: return True
        if match['awayteam__team_name'] in str(team1.team):
            if match['away_goals'] > match['home_goals']: return True
    return False

class PlayerStatDetailView(ListView):
    context_object_name = 'player_stat_list'

    def get_queryset(self):
        return Stat.objects.filter(team__season__is_current_season=True)
        #return Stat.objects.all()

    def get_context_data(self, **kwargs):
        context = super(PlayerStatDetailView, self).get_context_data(**kwargs)
        season = self.kwargs.get('season','0')
        context['seasons'] = Season.objects.order_by('-year','-season_type')[:4]
        context['active_season'] = int(season)
        context['player_stat_list'] = OrderedDict()
        for div in Division.objects.all():
            players = Player.objects.filter(roster__team__division=div)
            context['player_stat_list'][str(div)] = get_player_stats(
                    players, context['active_season']).filter(
                    sum_games_played__gte=1).order_by(
                    '-total_points', '-sum_goals', '-sum_assists', 'average_goals_against')
        return context

def get_player_stats(players, season):
    if season == 0:
        return players.values(
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
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__goals',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_assists=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__assists',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    total_points=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__assists', 0)+Coalesce('stat__goals',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_goals_against=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__goals_against', 0)-Coalesce('stat__empty_net', 0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_games_played=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True, then=1),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    average_goals_against=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True,
                                    then=Coalesce('stat__goals_against', 0.0)-Coalesce('stat__empty_net', 0.0)),
                            default=0.0,
                            output_field=DecimalField(),
                        )
                    )/Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__is_active=True, then=1.0),
                            default=0.00001,
                            output_field=DecimalField(),
                        )
                    ),
                    )
    else:
        return players.filter(
                    Q(stat__isnull=True) | Q(stat__matchup__is_postseason=False)).values(
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
                            When(stat__team=F('roster__team'), stat__team__season__id=season,
                                    then=Coalesce('stat__goals',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_assists=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__season__id=season,
                                    then=Coalesce('stat__assists',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    total_points=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__season__id=season,
                                    then=Coalesce('stat__assists', 0)+Coalesce('stat__goals',0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_goals_against=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__season__id=season,
                                    then=Coalesce('stat__goals_against', 0)-Coalesce('stat__empty_net', 0)),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    sum_games_played=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__season__id=season, then=1),
                            default=0,
                            output_field=IntegerField(),
                        )
                    ),
                    average_goals_against=Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__season__id=season,
                                    then=Coalesce('stat__goals_against', 0.0)-Coalesce('stat__empty_net', 0.0)),
                            default=0.0,
                            output_field=DecimalField(),
                        )
                    )/Sum(
                        Case(
                            When(stat__team=F('roster__team'), stat__team__season__id=season, then=1.0),
                            default=0.0001,
                            output_field=DecimalField(),
                        )
                    ),
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
            home_wins=Max('hometeam__team_stat__win')).annotate(
            home_losses=Max('hometeam__team_stat__loss')).annotate(
            home_ties=Max('hometeam__team_stat__tie')).annotate(
            away_wins=Max('awayteam__team_stat__win')).annotate(
            away_losses=Max('awayteam__team_stat__loss')).annotate(
            away_ties=Max('awayteam__team_stat__tie')):
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
            home_wins=Max('hometeam__team_stat__win')).annotate(
            home_losses=Max('hometeam__team_stat__loss')).annotate(
            home_ties=Max('hometeam__team_stat__tie')).annotate(
            away_wins=Max('awayteam__team_stat__win')).annotate(
            away_losses=Max('awayteam__team_stat__loss')).annotate(
            away_ties=Max('awayteam__team_stat__tie')):
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
            wins=Max('team_stat__win'),
            losses=Max('team_stat__loss'),
            ties=Max('team_stat__tie')).get(id=team)
    scorematchups = get_matches_for_team(team).filter(
            week__date__lte=datetime.datetime.today())
    scorematchups = add_goals_for_matchups(scorematchups)
    context['matchups'] = get_detailed_matchups(scorematchups)
    context['roster'] = []
    players = Player.objects.filter(roster__team__id=team)
    season = players.values_list('roster__team__season__id', flat=True).distinct()
    context['player_list'] = get_player_stats(players, int(season[0])).order_by(
            '-total_points', '-sum_goals', '-sum_assists', 'average_goals_against')
    for rosteritem in Roster.objects.select_related('team').select_related('player').filter(team__id=team):
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

def player(request, player=0):
    context = {}
    player_id = int(player)
    context['view'] = "player"
    player = Player.objects.filter(id=player_id)
    context['player'] = player
    context['career_stats'] = get_career_stats_for_player(player_id)
    context['seasons'] = get_seasons_played(player_id)
    context['goalie_stats'] = get_goalie_stats(player_id)
    context['offensive_stats'] = get_offensive_stats_for_player(player_id)

    return render(request, "leagues/player.html", context=context)

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
                output_field=DecimalField())
        )
    return Stat.objects.filter(player_id=player_id).aggregate(
            career_goals=Sum('goals'), 
            career_assists=Sum('assists'),
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
    count = Roster.objects.filter(player__id=player).count()
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
        'team__team_stat__win',
        'team__team_stat__loss',
        'team__team_stat__tie',
        'team__season__year', 
        'team__season__season_type',
        'team__division').annotate(
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
  

