"""planning/views.py"""

from django.shortcuts import render
from django.views.generic import TemplateView
from django.db.models import Q
from datetime import date
from isoweek import Week

from reference.models import Block, BlockType
from .models import Planting, PlanningYear


class PlanningMatrixView(TemplateView):
    template_name = "planning/matrix.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        year_obj = PlanningYear.objects.filter(status__in=["planning", "active"]).first()

        if not year_obj:
            ctx["no_year"] = True
            return ctx

        year = year_obj.year

        # Current or requested week
        requested_week = kwargs.get("week")
        if requested_week:
            center_week = requested_week
        else:
            today = date.today()
            if today.year == year:
                center_week = today.isocalendar()[1]
            else:
                center_week = 1

        # Show 16-week window (scrollable)
        week_start = max(1, center_week - 4)
        week_end = min(52, week_start + 15)
        weeks = list(range(week_start, week_end + 1))

        # Week metadata (dates, events)
        week_info = []
        for w in weeks:
            monday = Week(year, w).monday()
            week_info.append(
                {
                    "num": w,
                    "date": monday,
                    "is_current": (
                        w == date.today().isocalendar()[1] and year == date.today().year
                    ),
                }
            )

        # All blocks, grouped by type
        blocks = Block.objects.all().order_by("walk_route_order", "name")
        field_blocks = blocks.filter(block_type=BlockType.FIELD)
        tunnel_blocks = blocks.filter(block_type=BlockType.HIGH_TUNNEL)
        greenhouse_blocks = blocks.filter(block_type=BlockType.GREENHOUSE)

        # All plantings this year that overlap the visible window
        # Convert week range to dates for query
        window_start = Week(year, week_start).monday()
        window_end = Week(year, week_end).sunday()

        plantings = (
            Planting.objects.filter(
                planning_year=year_obj,
            )
            .exclude(status="skipped")
            .filter(
                # Planting overlaps visible window:
                # plant date before window end AND last harvest after window start
                Q(planned_plant_date__lte=window_end)
                & Q(planned_last_harvest_date__gte=window_start)
            )
            .select_related("crop", "crop_season", "block")
            .order_by("block__name", "bed_start", "planned_plant_date")
        )

        # Build the matrix: block → list of plantings with week positions
        matrix = self._build_matrix(blocks, plantings, weeks, year)

        ctx.update(
            {
                "year": year_obj,
                "weeks": week_info,
                "week_start": week_start,
                "week_end": week_end,
                "center_week": center_week,
                "field_blocks": field_blocks,
                "tunnel_blocks": tunnel_blocks,
                "greenhouse_blocks": greenhouse_blocks,
                "matrix": matrix,
                "plantings": plantings,
            }
        )
        return ctx

    def _build_matrix(self, blocks, plantings, weeks, year):
        """Build a dict: block_id → list of planting display objects."""
        matrix = {}

        for block in blocks:
            block_plantings = [p for p in plantings if p.block_id == block.id]
            rows = []

            for p in block_plantings:
                plant_week = p.planned_plant_date.isocalendar()[1]
                harvest_start = p.planned_first_harvest_date.isocalendar()[1]
                harvest_end = p.planned_last_harvest_date.isocalendar()[1]

                # Position in the grid
                first_visible = max(weeks[0], plant_week)
                last_visible = min(weeks[-1], harvest_end)

                if last_visible < first_visible:
                    continue  # Not visible in current window

                rows.append(
                    {
                        "planting": p,
                        "label": f"{p.crop.name}",
                        "sublabel": f"b{p.bed_start}-{p.bed_end}",
                        "col_start": first_visible - weeks[0],
                        "col_span": last_visible - first_visible + 1,
                        "plant_week": plant_week,
                        "harvest_start": harvest_start,
                        "harvest_end": harvest_end,
                        "status": p.status,
                        "css_class": self._status_css(p, weeks),
                    }
                )

            matrix[block.id] = rows

        return matrix

    def _status_css(self, planting, weeks):
        """Determine CSS class for planting bar."""
        current_week = date.today().isocalendar()[1]
        plant_wk = planting.planned_plant_date.isocalendar()[1]
        harvest_start = planting.planned_first_harvest_date.isocalendar()[1]
        harvest_end = planting.planned_last_harvest_date.isocalendar()[1]

        if planting.status == "failed":
            return "planting-failed"
        if planting.status == "revised":
            return "planting-revised"
        if planting.status == "complete":
            return "planting-complete"
        if current_week > harvest_end:
            return "planting-past"
        elif current_week >= harvest_start:
            return "planting-harvesting"
        elif current_week >= plant_wk:
            return "planting-growing"
        else:
            return "planting-planned"


# planning/views.py (additional views for HTMX)

from django.views.generic import DetailView, CreateView, UpdateView
from django.http import HttpResponse


class PlantingDetailView(DetailView):
    """HTMX partial: planting detail panel."""

    model = Planting
    template_name = "planning/partials/planting_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = self.object
        ctx["nursery_events"] = p.nursery_events.all()
        ctx["harvest_events"] = p.harvest_events.all()[:8]
        ctx["field_walk_notes"] = p.field_walk_notes.order_by("-walk_date")[:5]

        # Rotation check
        from core.models import RotationRule, RotationHistory

        family = p.crop.botanical_family
        if family:
            rule = RotationRule.objects.filter(botanical_family=family).first()
            history = (
                RotationHistory.objects.filter(block=p.block, botanical_family=family)
                .order_by("-year")
                .first()
            )

            if rule and history:
                gap = p.planning_year.year - history.year
                ctx["rotation_warning"] = gap < rule.min_gap_years
                ctx["rotation_gap"] = gap
                ctx["rotation_min"] = rule.min_gap_years
                ctx["rotation_last_year"] = history.year

        # Yield summary if actuals exist
        actual_harvests = p.harvest_events.filter(actual_quantity__isnull=False)
        if actual_harvests.exists():
            from django.db.models import Sum

            ctx["total_actual_yield"] = actual_harvests.aggregate(total=Sum("actual_quantity"))[
                "total"
            ]
            ctx["yield_per_bedfoot"] = (
                ctx["total_actual_yield"] / p.planned_bedfeet if p.planned_bedfeet else None
            )

        return ctx


class PlantingCreateView(CreateView):
    """Create a new planting. Handles both full-page and HTMX partial."""

    model = Planting
    template_name = "planning/partials/planting_form.html"
    fields = [
        "crop",
        "crop_season",
        "variety",
        "block",
        "bed_start",
        "bed_end",
        "planned_plant_date",
    ]

    def get_initial(self):
        initial = super().get_initial()
        year_obj = PlanningYear.objects.filter(status__in=["planning", "active"]).first()
        initial["planning_year"] = year_obj

        # Pre-fill from URL params (clicked cell in matrix)
        block_id = self.kwargs.get("block_id")
        week = self.kwargs.get("week")

        if block_id:
            block = Block.objects.get(id=block_id)
            initial["block"] = block
            initial["bed_start"] = 1
            initial["bed_end"] = block.num_beds

        if week and year_obj:
            initial["planned_plant_date"] = Week(year_obj.year, week).monday()

        return initial

    def form_valid(self, form):
        planting = form.save(commit=False)
        year_obj = PlanningYear.objects.filter(status__in=["planning", "active"]).first()
        planting.planning_year = year_obj

        # Auto-calculate bedfeet
        block = planting.block
        beds = planting.bed_end - planting.bed_start + 1
        planting.planned_bedfeet = beds * block.bedfeet_per_bed

        planting.save()

        # Generate nursery and harvest events
        planting.generate_nursery_events()
        planting.generate_harvest_events()

        if self.request.headers.get("HX-Request"):
            # HTMX: return the detail panel for the new planting
            return HttpResponse(
                status=204,
                headers={
                    "HX-Trigger": "plantingCreated",
                    "HX-Redirect": reverse("planning:matrix"),
                },
            )
        return redirect("planning:matrix")
