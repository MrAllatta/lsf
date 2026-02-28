"""planning/urls.py"""

from django.urls import path
from . import views

app_name = "planning"

urlpatterns = [
    # Main planning view — the week×block matrix
    path("", views.PlanningMatrixView.as_view(), name="matrix"),
    path("week/<int:week>/", views.PlanningMatrixView.as_view(), name="matrix_week"),
    # Planting CRUD
    path("planting/new/", views.PlantingCreateView.as_view(), name="planting_create"),
    path(
        "planting/new/block/<int:block_id>/week/<int:week>/",
        views.PlantingCreateView.as_view(),
        name="planting_create_prefilled",
    ),
    path("planting/<int:pk>/", views.PlantingDetailView.as_view(), name="planting_detail"),
    path("planting/<int:pk>/edit/", views.PlantingUpdateView.as_view(), name="planting_edit"),
    path("planting/<int:pk>/revise/", views.PlantingReviseView.as_view(), name="planting_revise"),
    # Succession series
    path("succession/new/", views.SuccessionCreateView.as_view(), name="succession_create"),
    # Generated schedules
    path("nursery/", views.NurseryScheduleView.as_view(), name="nursery_schedule"),
    path("nursery/week/<int:week>/", views.NurseryScheduleView.as_view(), name="nursery_week"),
    path("field-schedule/", views.FieldScheduleView.as_view(), name="field_schedule"),
    path(
        "field-schedule/week/<int:week>/",
        views.FieldScheduleView.as_view(),
        name="field_schedule_week",
    ),
    path("harvest-calendar/", views.HarvestCalendarView.as_view(), name="harvest_calendar"),
]
