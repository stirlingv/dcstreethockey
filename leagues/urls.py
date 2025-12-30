from django.urls import path
from .views import goalie_status_board, captain_goalie_update, update_goalie_status

urlpatterns = [
    # Public goalie status board
    path("goalie-status/", goalie_status_board, name="goalie_status_board"),
    # Captain's update page (authenticated via secret URL)
    path(
        "goalie-status/captain/<uuid:access_code>/",
        captain_goalie_update,
        name="captain_goalie_update",
    ),
    # AJAX endpoint for updating goalie status
    path(
        "goalie-status/captain/<uuid:access_code>/update/<int:matchup_id>/",
        update_goalie_status,
        name="update_goalie_status",
    ),
]
