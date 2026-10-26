from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from screening import views as screening_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Listed before allauth's own routes so these win. This system stores no
    # password, so a page offering to change or reset one describes something
    # that does not exist; allauth registers them regardless of whether any
    # account has one. They redirect to the profile with an explanation rather
    # than 404, because someone reaching them followed a link and deserves to
    # know why it leads nowhere.
    path(
        "accounts/password/change/",
        screening_views.no_password_here,
        name="account_change_password",
    ),
    path(
        "accounts/password/set/",
        screening_views.no_password_here,
        name="account_set_password",
    ),
    path(
        "accounts/password/reset/",
        screening_views.no_password_here,
        name="account_reset_password",
    ),
    path("accounts/", include("allauth.urls")),
    path("", include("screening.urls")),
]

# Uploaded radiographs and the heatmaps built from them are served by the
# application rather than by a static route, in every environment.
#
# They were previously handed out by django.conf.urls.static.static() in
# development and by nothing at all in the packaged build, which meant they
# were either public to anyone who knew the address or unreachable even to the
# person who uploaded them. Both are wrong for patient imaging. The view checks
# the session and the clinic, so an image is exactly as visible as the case
# page that shows it.
urlpatterns += [
    re_path(
        rf"^{settings.MEDIA_URL.lstrip('/')}(?P<path>.*)$",
        screening_views.protected_media,
        name="protected_media",
    )
]
