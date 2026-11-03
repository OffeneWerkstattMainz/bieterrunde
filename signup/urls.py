from django.urls import path

from signup import views

urlpatterns = [
    path("bestaetigen/<str:token>/", views.confirm, name="confirm"),
]
