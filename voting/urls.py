from django.urls import path

from voting import views

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.voting_create, name="create"),
    path("manage/<int:voting_id>", views.voting_manage, name="manage"),
    path("manage/<int:voting_id>/new-round/", views.voting_new_round, name="new-round"),
    path("manage/<int:voting_id>/export/", views.voting_export, name="export"),
    path("info/<int:voting_id>", views.voting_info, name="info"),
    path("vote/<int:voting_id>", views.voting_vote, name="vote"),
    path("vote/<int:voting_id>/<int:voting_round_id>/", views.voting_vote, name="vote"),
    path("vote/<int:voting_id>/done", views.voting_vote_done, name="vote-done"),
]
