"""operations/urls.py"""

from django.urls import path
from . import views

app_name = "operations"

urlpatterns = [
    # Harvest entry
    path("harvest/", views.WeeklyHarvestEntryView.as_view(), name="harvest_entry_current"),
    path(
        "harvest/week/<int:week>/",
        views.WeeklyHarvestEntryView.as_view(),
        name="harvest_entry_week",
    ),
    path(
        "harvest/planting/<int:pk>/", views.PlantingHarvestEntryView.as_view(), name="harvest_entry"
    ),
    # Field walk
    path("field-walk/", views.FieldWalkView.as_view(), name="field_walk_current"),
    path("field-walk/planting/<int:pk>/", views.FieldWalkNoteView.as_view(), name="field_walk"),
    # Inventory
    path("inventory/", views.InventoryDashboardView.as_view(), name="inventory"),
    path("inventory/add/", views.InventoryTransactionView.as_view(), name="inventory_add"),
    path(
        "inventory/harvest-in/<int:harvest_event_id>/",
        views.InventoryHarvestInView.as_view(),
        name="inventory_harvest_in",
    ),
]
