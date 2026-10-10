from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("screening.urls")),
]

# Uploaded radiographs and heatmaps are served by Django in development and in
# the packaged desktop build, both of which run for a single local user. A
# deployment behind a web server would serve these from the server instead.
if settings.DEBUG or settings.PACKAGED:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
