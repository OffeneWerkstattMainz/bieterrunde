from django.urls import path

from voting import views

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.voting_create, name="create"),
    path("manage/<uuid:voting_id>", views.voting_manage, name="manage"),
    path("manage/<uuid:voting_id>/new-round/", views.voting_new_round, name="new-round"),
    path("manage/<uuid:voting_id>/import-bids/", views.voting_import_bids, name="import-bids"),
    path("manage/<uuid:voting_id>/voters/", views.voting_voters, name="voters"),
    path("manage/<uuid:voting_id>/voters/add/", views.voting_voter_add, name="voter-add"),
    path(
        "manage/<uuid:voting_id>/voters/quick-add/",
        views.voting_voter_quick_add,
        name="voter-quick-add",
    ),
    path(
        "manage/<uuid:voting_id>/voters/<int:voting_voter_id>/edit/",
        views.voting_voter_edit,
        name="voter-edit",
    ),
    path("manage/<uuid:voting_id>/export/", views.voting_export, name="export"),
    path("manage/<uuid:voting_id>/export/<int:round_id>/", views.voting_export, name="export"),
    path("info/<uuid:voting_id>", views.voting_info, name="info"),
    path("vote/<uuid:voting_id>", views.voting_vote, name="vote"),
    path("vote/<uuid:voting_id>/<int:voting_round_id>/", views.voting_vote, name="vote"),
    path(
        "registration/<uuid:voting_id>/<int:member_id>/<str:auth_token>/",
        views.voter_registration,
        name="voter-registration",
    ),
]
