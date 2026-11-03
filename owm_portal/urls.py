from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("convert", include("guest_user.urls")),
    path("bieterrunde/", include(("voting.urls", "voting"), namespace="voting")),
    path("anmeldung/", include(("signup.urls", "signup"), namespace="signup")),
    # The Bieterrunde used to live at the site root. Keep old links (e.g. registration links
    # sent to members) working.
    re_path(
        r"^(?P<path>(create|manage|info|vote|registration)/.*)$",
        RedirectView.as_view(url="/bieterrunde/%(path)s", permanent=True, query_string=True),
    ),
    path("", include(("core.urls", "core"), namespace="core")),
]
