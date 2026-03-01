# core/context_processors.py

from datetime import date
from planning.models import PlanningYear


def planning_context(request):
    """Add current planning year and week to every template."""
    year_obj = PlanningYear.objects.filter(status__in=["planning", "active"]).first()

    today = date.today()
    current_week = today.isocalendar()[1]

    return {
        "current_planning_year": year_obj,
        "current_week": current_week,
        "today": today,
    }
