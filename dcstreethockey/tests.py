from django.test import TestCase, RequestFactory
from django.urls import reverse
from core.views import PlayerStatDetailView
from leagues.models import Season, Division, Player, Team, Stat

class PlayerStatDetailViewTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.season = Season.objects.create(year=2023, season_type='Regular', is_current_season=True)
        self.division = Division.objects.create(name='Test Division')
        self.team = Team.objects.create(team_name='Test Team', division=self.division, season=self.season)
        self.player = Player.objects.create(first_name='John', last_name='Doe')
        self.stat = Stat.objects.create(player=self.player, team=self.team, goals=5, assists=3, games_played=2)

    def test_get_queryset(self):
        request = self.factory.get(reverse('your-view-name'))
        view = PlayerStatDetailView()
        view.request = request

        queryset = view.get_queryset()
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first(), self.stat)

    def test_get_context_data(self):
        request = self.factory.get(reverse('your-view-name'))
        view = PlayerStatDetailView()
        view.request = request

        response = view.get(request)
        context = response.context_data

        self.assertIn('seasons', context)
        self.assertIn('active_season', context)
        self.assertIn('player_stat_list', context)
        self.assertEqual(context['active_season'], 0)

        player_stat_list = context['player_stat_list']
        self.assertIn(str(self.division), player_stat_list)
        self.assertEqual(len(player_stat_list[str(self.division)]), 1)
        self.assertEqual(player_stat_list[str(self.division)][0]['first_name'], 'John')
        self.assertEqual(player_stat_list[str(self.division)][0]['last_name'], 'Doe')
