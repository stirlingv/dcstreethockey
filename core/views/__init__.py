from .home import home, leagues
from .players import (
    PlayerAllTimeStats_list,
    PlayerAutocomplete,
    PlayerStatDetailView,
    calculate_player_stats,
    filter_stats_by_scope,
    get_average_stats_for_player,
    get_player_stats,
    normalize_stat_scope,
    player_trends_view,
    player_view,
)
from .schedule import MatchUpDetailView, cups, schedule, scores, teams
from .standings import TeamStatDetailView
