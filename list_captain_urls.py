from leagues.models import Team

print("Active Teams and Captain URLs:")
for t in Team.objects.filter(is_active=True):
    print(
        f"{t.team_name}: http://127.0.0.1:8000/goalie-status/captain/{t.captain_access_code}/"
    )
