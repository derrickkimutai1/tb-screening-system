from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
