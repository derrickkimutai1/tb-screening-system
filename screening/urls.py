from django.urls import path

from . import views

app_name = "screening"

urlpatterns = [
    path("", views.upload, name="upload"),
    path("cases/", views.case_list, name="case_list"),
    path("cases/<uuid:case_id>/", views.case_detail, name="case_detail"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("health/", views.health, name="health"),
    path("restart-sign-in/", views.restart_sign_in, name="restart_sign_in"),
]
