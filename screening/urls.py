from django.urls import path

from . import views

app_name = "screening"

urlpatterns = [
    path("", views.upload, name="upload"),
    path("worklist/", views.worklist, name="worklist"),
    path("cases/", views.case_list, name="case_list"),
    path("cases/export/", views.export_cases, name="export_cases"),
    path("cases/<uuid:case_id>/", views.case_detail, name="case_detail"),
    path(
        "cases/<uuid:case_id>/explanation/",
        views.case_explanation,
        name="case_explanation",
    ),
    path("cases/<uuid:case_id>/report/", views.case_report, name="case_report"),
    path("trail/", views.access_trail, name="access_trail"),
    path("trail/verify/", views.verify_access_trail, name="verify_access_trail"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("health/", views.health, name="health"),
    path("restart-sign-in/", views.restart_sign_in, name="restart_sign_in"),
    path("continue/", views.continue_with_email, name="continue_with_email"),
]
