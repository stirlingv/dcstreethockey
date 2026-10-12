"""
A small but complete league used by the site-wide smoke tests.

It creates at least one row for every model registered in the admin, so the
admin sweep can open each change page and the public URL sweep can fill in
every URL argument. Used in two places:

- ``dcstreethockey/test_smoke.py`` builds it inside the test database.
- ``manage.py seed_smoke_data`` builds it in a real Postgres database for the
  production-settings smoke job in CI.
"""

import datetime

from django.contrib.auth.models import Group
from django.utils import timezone

from leagues.models import (
    Division,
    DraftChatMessage,
    DraftPick,
    DraftRound,
    DraftSession,
    DraftTeam,
    HomePage,
    MatchUp,
    PendingPlayerPhoto,
    PendingTeamPhoto,
    Player,
    PlayerPhoto,
    Ref,
    Roster,
    Season,
    SeasonSignup,
    Stat,
    Team,
    Team_Stat,
    TeamPhoto,
    Week,
)

CENTER, WING, DEFENSE, GOALIE = 1, 2, 3, 4


def build_smoke_data():
    """Create the smoke-test league and return the key objects by name."""
    today = timezone.localdate()

    Group.objects.get_or_create(name="Smoke Test Group")
    HomePage.objects.create(announcement="Welcome to the smoke-test season")

    season = Season.objects.create(
        year=today.year, season_type=3, is_current_season=True
    )
    division = Division.objects.create(division=1)

    team_photo = TeamPhoto.objects.create(photo="team_photos/smoke.jpg")
    home = Team.objects.create(
        team_name="Smoke Home",
        team_color="Blue",
        division=division,
        season=season,
        is_active=True,
        team_photo=team_photo,
    )
    away = Team.objects.create(
        team_name="Smoke Away",
        team_color="Orange",
        division=division,
        season=season,
        is_active=True,
    )

    player_photo = PlayerPhoto.objects.create(photo="player_photos/smoke.jpg")
    players = {}
    for team, prefix in ((home, "Home"), (away, "Away")):
        for position, label in ((CENTER, "Center"), (DEFENSE, "Defense")):
            player = Player.objects.create(
                first_name=f"{prefix}", last_name=f"{label}", email="p@example.com"
            )
            Roster.objects.create(
                player=player,
                team=team,
                position1=position,
                is_captain=position == CENTER,
                player_number=position,
            )
            players[f"{prefix.lower()}_{label.lower()}"] = player
        goalie = Player.objects.create(
            first_name=prefix, last_name="Goalie", can_play_goalie=True
        )
        Roster.objects.create(
            player=goalie, team=team, position1=GOALIE, is_primary_goalie=True
        )
        players[f"{prefix.lower()}_goalie"] = goalie
    players["home_center"].player_photo = player_photo
    players["home_center"].save()

    PendingPlayerPhoto.objects.create(
        player=players["away_center"], photo="pending/smoke_player.jpg"
    )
    PendingTeamPhoto.objects.create(team=away, photo="pending/smoke_team.jpg")

    ref = Ref.objects.create(player=players["away_defense"])

    past_week = Week.objects.create(
        division=division, season=season, date=today - datetime.timedelta(days=7)
    )
    next_week = Week.objects.create(
        division=division, season=season, date=today + datetime.timedelta(days=7)
    )
    played = MatchUp.objects.create(
        week=past_week,
        time=datetime.time(10, 0),
        hometeam=home,
        awayteam=away,
        home_goalie=players["home_goalie"],
        away_goalie=players["away_goalie"],
    )
    upcoming = MatchUp.objects.create(
        week=next_week,
        time=datetime.time(11, 0),
        hometeam=away,
        awayteam=home,
    )
    Stat.objects.create(
        player=players["home_center"], team=home, matchup=played, goals=2, assists=1
    )
    Stat.objects.create(
        player=players["away_center"], team=away, matchup=played, goals=1
    )
    Stat.objects.create(
        player=players["home_goalie"], team=home, matchup=played, goals_against=1
    )
    Stat.objects.create(
        player=players["away_goalie"], team=away, matchup=played, goals_against=2
    )
    Team_Stat.objects.create(
        division=division,
        season=season,
        team=home,
        win=1,
        goals_for=2,
        goals_against=1,
    )
    Team_Stat.objects.create(
        division=division,
        season=season,
        team=away,
        loss=1,
        goals_for=1,
        goals_against=2,
    )

    draft_season = Season.objects.create(
        year=today.year, season_type=4, is_current_season=False
    )
    draft = DraftSession.objects.create(
        season=draft_season,
        num_teams=2,
        num_rounds=2,
        state=DraftSession.STATE_ACTIVE,
        signups_open=True,
    )
    signups = [
        SeasonSignup.objects.create(
            season=draft_season,
            first_name=f"Signup{i}",
            last_name="Player",
            email=f"signup{i}@example.com",
            primary_position=position,
            secondary_position=0,
            captain_interest=i < 2,
        )
        for i, position in enumerate((CENTER, WING, DEFENSE, GOALIE))
    ]
    draft_teams = [
        DraftTeam.objects.create(
            session=draft,
            captain=signups[i],
            team_name=f"Draft Team {i + 1}",
            draft_position=i + 1,
            captain_draft_round=1,
        )
        for i in range(2)
    ]
    for round_number in (1, 2):
        DraftRound.objects.create(session=draft, round_number=round_number)
    DraftPick.objects.create(
        session=draft,
        team=draft_teams[0],
        signup=signups[0],
        round_number=1,
        pick_number=1,
        is_auto_captain=True,
    )
    DraftChatMessage.objects.create(
        session=draft,
        sender_name="Commissioner",
        sender_type="commissioner",
        body="Smoke test draft is live",
    )

    return {
        "season": season,
        "division": division,
        "home": home,
        "away": away,
        "players": players,
        "ref": ref,
        "played": played,
        "upcoming": upcoming,
        "draft_season": draft_season,
        "draft": draft,
        "draft_teams": draft_teams,
        "signups": signups,
    }
