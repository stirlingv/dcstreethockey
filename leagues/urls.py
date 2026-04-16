from django.urls import path
from .views import (
    goalie_status_board,
    captain_goalie_update,
    update_goalie_status,
    captain_urls_list,
)
from .draft_views import (
    draft_signup,
    draft_board_spectator,
    draft_board_commissioner,
    draft_board_captain,
    draft_captain_portal,
    draw_positions,
    advance_state,
    undo_last_pick,
    make_pick,
    finalize_draft,
    swap_pick,
    reset_draft,
    set_captain_rounds,
    email_team_data,
)

urlpatterns = [
    # -----------------------------------------------------------------------
    # Goalie status
    # -----------------------------------------------------------------------
    path("goalie-status/", goalie_status_board, name="goalie_status_board"),
    path(
        "goalie-status/captain/<uuid:access_code>/",
        captain_goalie_update,
        name="captain_goalie_update",
    ),
    path(
        "goalie-status/captain/<uuid:access_code>/update/<int:matchup_id>/",
        update_goalie_status,
        name="update_goalie_status",
    ),
    path("captain-urls/", captain_urls_list, name="captain_urls_list"),
    # -----------------------------------------------------------------------
    # Wednesday Draft League – Signup
    # -----------------------------------------------------------------------
    path(
        "draft/signup/<int:season_pk>/",
        draft_signup,
        name="draft_signup",
    ),
    # -----------------------------------------------------------------------
    # Wednesday Draft League – Draft Board views
    # -----------------------------------------------------------------------
    path(
        "draft/<int:session_pk>/",
        draft_board_spectator,
        name="draft_board_spectator",
    ),
    path(
        "draft/<int:session_pk>/commissioner/<uuid:token>/",
        draft_board_commissioner,
        name="draft_board_commissioner",
    ),
    path(
        "draft/<int:session_pk>/captain/<uuid:token>/",
        draft_board_captain,
        name="draft_board_captain",
    ),
    path(
        "draft/<int:session_pk>/captains/",
        draft_captain_portal,
        name="draft_captain_portal",
    ),
    # -----------------------------------------------------------------------
    # Wednesday Draft League – API endpoints (POST / commissioner actions)
    # -----------------------------------------------------------------------
    path(
        "draft/<int:session_pk>/draw/<uuid:token>/",
        draw_positions,
        name="draft_draw_positions",
    ),
    path(
        "draft/<int:session_pk>/advance/<uuid:token>/",
        advance_state,
        name="draft_advance_state",
    ),
    path(
        "draft/<int:session_pk>/undo/<uuid:token>/",
        undo_last_pick,
        name="draft_undo_pick",
    ),
    path(
        "draft/<int:session_pk>/pick/",
        make_pick,
        name="draft_make_pick",
    ),
    path(
        "draft/<int:session_pk>/finalize/<uuid:token>/",
        finalize_draft,
        name="draft_finalize",
    ),
    path(
        "draft/<int:session_pk>/swap/<uuid:token>/",
        swap_pick,
        name="draft_swap_pick",
    ),
    path(
        "draft/<int:session_pk>/reset/<uuid:token>/",
        reset_draft,
        name="draft_reset",
    ),
    path(
        "draft/<int:session_pk>/captain-rounds/<uuid:token>/",
        set_captain_rounds,
        name="draft_set_captain_rounds",
    ),
    path(
        "draft/<int:session_pk>/my-team/<uuid:token>/",
        email_team_data,
        name="draft_email_team",
    ),
]
