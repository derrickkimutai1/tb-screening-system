from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

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
elif settings.PACKAGED:
    # The desktop build has to serve the radiographs and heatmaps itself.
    #
    # django.conf.urls.static.static() above returns nothing unless DEBUG, and
    # WhiteNoise serves only the collected static files, so with neither in
    # play every image on a result page was a broken icon: the files were
    # written to the data folder correctly and nothing would hand them back.
    #
    # Django's own warning about this view is about serving media from a public
    # web server, where a dedicated server should do it. This build is a single
    # process bound to the loopback interface on one person's machine, serving
    # that person their own uploads, so the warning does not describe this
    # situation. A deployed instance never reaches here, because PACKAGED is
    # false and the media sits behind the platform's own storage.
    urlpatterns += [
        re_path(
            rf"^{settings.MEDIA_URL.lstrip('/')}(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        )
    ]
