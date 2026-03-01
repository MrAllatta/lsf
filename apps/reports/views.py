"""reports/views.py"""

from django.views.generic import TemplateView
from django.db.models import Sum, F, Q
from datetime import date, timedelta
from isoweek import Week
import math

from planning.models import HarvestEvent, PlanningYear
from reference.models import Block


class RevenueProjectionView(TemplateView):
    """Project weekly revenue from planned plantings × sales formats."""

    template_name = "reports/revenue_projection.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        year_obj = PlanningYear.objects.filter(status__in=["planning", "active"]).first()
        year = year_obj.year

        channels = SalesChannel.objects.all()

        # Build weekly harvest availability: week → crop → quantity
        harvest_events = (
            HarvestEvent.objects.filter(
                planting__planning_year=year_obj,
            )
            .exclude(planting__status__in=["skipped", "failed", "revised"])
            .select_related("planting__crop", "planting__crop_season")
        )

        # Aggregate expected harvest by week and crop
        weekly_supply = {}  # week_num → {crop_id: total_qty}
        for he in harvest_events:
            wk = he.planned_date.isocalendar()[1]
            crop_id = he.planting.crop_id

            if wk not in weekly_supply:
                weekly_supply[wk] = {}

            qty = float(he.actual_quantity or he.planned_quantity or 0)
            weekly_supply[wk][crop_id] = weekly_supply[wk].get(crop_id, 0) + qty

        # Get all active sales formats with their prices
        formats = CropSalesFormat.objects.filter(is_active=True).select_related("crop")

        # Build format lookup: crop_id → best format (highest price)
        crop_formats = {}
        for f in formats:
            if f.crop_id not in crop_formats:
                crop_formats[f.crop_id] = f
            elif f.sale_price > crop_formats[f.crop_id].sale_price:
                crop_formats[f.crop_id] = f

        # Project revenue per week
        weekly_projections = []
        annual_projected = Decimal("0")
        annual_target = sum(ch.annual_target for ch in channels)

        for wk in range(1, 53):
            supply = weekly_supply.get(wk, {})

            week_revenue = Decimal("0")
            week_products = []

            for crop_id, qty in supply.items():
                fmt = crop_formats.get(crop_id)
                if fmt:
                    sale_units = Decimal(str(qty)) / fmt.harvest_qty_per_sale_unit
                    revenue = sale_units * fmt.sale_price
                    week_revenue += revenue
                    week_products.append(
                        {
                            "crop_name": fmt.crop.name,
                            "quantity": qty,
                            "harvest_unit": fmt.crop.harvest_unit,
                            "revenue": revenue,
                        }
                    )

            # Compare to channel targets for this week
            week_target = Decimal("0")
            for ch in channels:
                if ch.start_week <= wk <= ch.end_week:
                    week_target += ch.weekly_target

            gap = week_revenue - week_target
            annual_projected += week_revenue

            monday = Week(year, wk).monday()

            weekly_projections.append(
                {
                    "week": wk,
                    "date": monday,
                    "projected_revenue": week_revenue,
                    "target": week_target,
                    "gap": gap,
                    "gap_pct": (gap / week_target * 100) if week_target else 0,
                    "num_products": len(week_products),
                    "products": sorted(week_products, key=lambda x: x["revenue"], reverse=True)[:5],
                }
            )

        # Identify problem periods
        gap_weeks = [w for w in weekly_projections if w["gap"] < 0]
        surplus_weeks = [w for w in weekly_projections if w["gap"] > 0]

        ctx.update(
            {
                "year": year_obj,
                "channels": channels,
                "weekly": weekly_projections,
                "annual_projected": annual_projected,
                "annual_target": annual_target,
                "annual_gap": annual_projected - annual_target,
                "gap_weeks": len(gap_weeks),
                "surplus_weeks": len(surplus_weeks),
                "worst_gap_week": min(gap_weeks, key=lambda w: w["gap"]) if gap_weeks else None,
                "best_surplus_week": (
                    max(surplus_weeks, key=lambda w: w["gap"]) if surplus_weeks else None
                ),
            }
        )
        return ctx


class ChannelPerformanceView(TemplateView):
    """Revenue by channel — weekly, monthly, annual vs target."""

    template_name = "reports/channel_performance.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        year_obj = PlanningYear.objects.filter(status__in=["active", "complete"]).first()
        year = year_obj.year

        channels = SalesChannel.objects.all()

        channel_data = []

        for channel in channels:
            # Get all weeks this channel is active
            active_weeks = list(range(channel.start_week, channel.end_week + 1))

            # Collect revenue per week (from detailed or quick entries)
            weekly_revenue = {}

            # From detailed sales events
            detailed = (
                SalesEvent.objects.filter(
                    channel=channel,
                    sale_date__year=year,
                    actual_revenue__isnull=False,
                )
                .values("sale_date")
                .annotate(day_total=Sum("actual_revenue"))
            )

            for row in detailed:
                wk = row["sale_date"].isocalendar()[1]
                weekly_revenue[wk] = weekly_revenue.get(wk, Decimal("0")) + row["day_total"]

            # From quick entries (fills gaps where detailed not used)
            quick = QuickSalesEntry.objects.filter(
                channel=channel,
                sale_date__year=year,
            )

            for qe in quick:
                wk = qe.sale_date.isocalendar()[1]
                # Only use quick entry if no detailed entries for this week
                if wk not in weekly_revenue:
                    weekly_revenue[wk] = qe.total_revenue

            # Build week-by-week table
            weeks_table = []
            ytd_revenue = Decimal("0")
            ytd_target = Decimal("0")

            for wk in active_weeks:
                revenue = weekly_revenue.get(wk, None)
                target = channel.weekly_target

                ytd_target += target
                if revenue is not None:
                    ytd_revenue += revenue

                gap = (revenue - target) if revenue is not None else None

                weeks_table.append(
                    {
                        "week": wk,
                        "date": Week(year, wk).monday(),
                        "revenue": revenue,
                        "target": target,
                        "gap": gap,
                        "gap_pct": (gap / target * 100) if gap is not None and target else None,
                        "has_data": revenue is not None,
                    }
                )

            # Monthly aggregates
            monthly = {}
            for row in weeks_table:
                month = row["date"].month
                if month not in monthly:
                    monthly[month] = {
                        "month": month,
                        "month_name": row["date"].strftime("%B"),
                        "revenue": Decimal("0"),
                        "target": Decimal("0"),
                        "weeks": 0,
                        "weeks_with_data": 0,
                    }
                monthly[month]["target"] += row["target"]
                monthly[month]["weeks"] += 1
                if row["revenue"] is not None:
                    monthly[month]["revenue"] += row["revenue"]
                    monthly[month]["weeks_with_data"] += 1

            # Sell-through analysis (only if detailed sales exist)
            sellthrough_data = None
            if SalesEvent.objects.filter(
                channel=channel,
                sale_date__year=year,
                brought_quantity__isnull=False,
            ).exists():
                st = SalesEvent.objects.filter(
                    channel=channel,
                    sale_date__year=year,
                    brought_quantity__isnull=False,
                    brought_quantity__gt=0,
                ).aggregate(
                    total_brought=Sum("brought_quantity"),
                    total_sold=Sum("actual_quantity"),
                )

                if st["total_brought"]:
                    sellthrough_data = {
                        "total_brought": st["total_brought"],
                        "total_sold": st["total_sold"],
                        "pct": (st["total_sold"] / st["total_brought"] * 100),
                    }

            # Top products by revenue
            top_products = (
                SalesEvent.objects.filter(
                    channel=channel,
                    sale_date__year=year,
                    actual_revenue__isnull=False,
                )
                .values(
                    "product__product_name",
                    "product__crop__name",
                )
                .annotate(
                    total_revenue=Sum("actual_revenue"),
                    total_qty=Sum("actual_quantity"),
                )
                .order_by("-total_revenue")[:10]
            )

            # Pacing analysis — are we on track?
            today = date.today()
            weeks_elapsed = sum(1 for w in weeks_table if w["date"] <= today and w["has_data"])
            weeks_remaining = sum(1 for w in weeks_table if w["date"] > today)

            on_pace = None
            if weeks_elapsed > 0:
                avg_actual = ytd_revenue / weeks_elapsed
                projected_annual = ytd_revenue + avg_actual * weeks_remaining
                on_pace = projected_annual >= channel.annual_target

                pacing_data = {
                    "avg_weekly": avg_actual,
                    "projected_annual": projected_annual,
                    "annual_target": channel.annual_target,
                    "on_pace": on_pace,
                    "gap_to_target": projected_annual - channel.annual_target,
                }
            else:
                pacing_data = None

            channel_data.append(
                {
                    "channel": channel,
                    "weeks_table": weeks_table,
                    "monthly": sorted(monthly.values(), key=lambda m: m["month"]),
                    "ytd_revenue": ytd_revenue,
                    "ytd_target": ytd_target,
                    "ytd_gap": ytd_revenue - ytd_target,
                    "annual_target": channel.annual_target,
                    "weeks_with_data": sum(1 for w in weeks_table if w["has_data"]),
                    "total_active_weeks": len(active_weeks),
                    "sellthrough": sellthrough_data,
                    "top_products": list(top_products),
                    "pacing": pacing_data,
                }
            )

        # Grand totals across all channels
        total_ytd = sum(cd["ytd_revenue"] for cd in channel_data)
        total_target_ytd = sum(cd["ytd_target"] for cd in channel_data)
        total_annual_target = sum(cd["annual_target"] for cd in channel_data)

        ctx.update(
            {
                "year": year_obj,
                "channels": channel_data,
                "total_ytd": total_ytd,
                "total_target_ytd": total_target_ytd,
                "total_annual_target": total_annual_target,
                "total_ytd_gap": total_ytd - total_target_ytd,
            }
        )
        return ctx


class SeasonSummaryView(TemplateView):
    """End-of-season overview — the post-season analysis dashboard."""

    template_name = "reports/season_summary.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        year_obj = PlanningYear.objects.filter(status__in=["active", "complete"]).first()
        year = year_obj.year

        # All plantings
        all_plantings = Planting.objects.filter(
            planning_year=year_obj,
        ).select_related("crop", "crop_season", "block")

        planned = all_plantings.exclude(status="skipped")
        completed = all_plantings.filter(status__in=["complete", "harvesting"])
        failed = all_plantings.filter(status="failed")
        skipped = all_plantings.filter(status="skipped")

        # Total bedfeet
        total_planned_bf = sum(p.planned_bedfeet for p in planned)
        total_actual_bf = sum(p.actual_bedfeet or p.planned_bedfeet for p in completed)

        # Yield summary
        harvest_totals = HarvestEvent.objects.filter(
            planting__planning_year=year_obj,
        ).aggregate(
            planned_yield=Sum("planned_quantity"),
            actual_yield=Sum("actual_quantity"),
        )

        planned_yield_total = harvest_totals["planned_yield"] or Decimal("0")
        actual_yield_total = harvest_totals["actual_yield"] or Decimal("0")

        # Revenue summary — all channels
        detailed_revenue = SalesEvent.objects.filter(
            sale_date__year=year,
            actual_revenue__isnull=False,
        ).aggregate(total=Sum("actual_revenue"))["total"] or Decimal("0")

        quick_revenue = QuickSalesEntry.objects.filter(
            sale_date__year=year,
        ).aggregate(
            total=Sum("total_cash") + Sum("total_card")
        )["total"] or Decimal("0")

        # Avoid double-counting: detailed sales take precedence by week
        # Get weeks covered by detailed sales
        detailed_weeks = set(
            SalesEvent.objects.filter(
                sale_date__year=year,
                actual_revenue__isnull=False,
            )
            .values_list("sale_date", flat=True)
            .distinct()
        )
        detailed_week_nums = {d.isocalendar()[1] for d in detailed_weeks}

        # Quick sales for weeks NOT covered by detailed
        quick_only = QuickSalesEntry.objects.filter(
            sale_date__year=year,
        ).exclude(
            sale_date__in=detailed_weeks
        ).aggregate(total=Sum("total_cash") + Sum("total_card"))["total"] or Decimal("0")

        total_revenue = detailed_revenue + quick_only

        annual_target = sum(ch.annual_target for ch in SalesChannel.objects.all())

        # Crops grown
        crop_types = set(p.crop.crop_type for p in planned if p.crop.crop_type)
        unique_crops = set(p.crop.name for p in planned)
        botanical_families = set(
            p.crop.botanical_family for p in planned if p.crop.botanical_family
        )

        # Harvest labor
        labor_totals = HarvestEvent.objects.filter(
            planting__planning_year=year_obj,
            actual_hours__isnull=False,
        ).aggregate(
            total_hours=Sum("actual_hours"),
        )
        total_harvest_hours = labor_totals["total_hours"] or Decimal("0")

        revenue_per_harvest_hour = (
            total_revenue / total_harvest_hours if total_harvest_hours else None
        )

        # Crop performance — top and bottom performers by $/bf
        crop_performance = {}

        for p in completed:
            crop_name = p.crop.name
            if crop_name not in crop_performance:
                crop_performance[crop_name] = {
                    "crop": p.crop,
                    "total_bf": 0,
                    "total_revenue": Decimal("0"),
                }

            bf = p.actual_bedfeet or p.planned_bedfeet
            crop_performance[crop_name]["total_bf"] += bf

            # Estimate revenue from harvest × price
            harvest = p.harvest_events.filter(actual_quantity__isnull=False).aggregate(
                total=Sum("actual_quantity")
            )["total"]

            if harvest:
                fmt = (
                    CropSalesFormat.objects.filter(crop=p.crop, is_active=True)
                    .order_by("-sale_price")
                    .first()
                )

                if fmt:
                    revenue = harvest / fmt.harvest_qty_per_sale_unit * fmt.sale_price
                    crop_performance[crop_name]["total_revenue"] += revenue

        for name, data in crop_performance.items():
            data["revenue_per_bf"] = (
                data["total_revenue"] / data["total_bf"] if data["total_bf"] else Decimal("0")
            )

        sorted_by_revenue = sorted(
            crop_performance.values(),
            key=lambda d: d["revenue_per_bf"],
            reverse=True,
        )

        top_10 = sorted_by_revenue[:10]
        bottom_10 = [c for c in sorted_by_revenue[-10:] if c["total_revenue"] > 0]

        # Rotation summary — update rotation history
        # (Could be automated at season completion)
        rotation_updates = {}
        for p in completed:
            family = p.crop.botanical_family
            if family and p.block_id:
                key = (p.block_id, family)
                rotation_updates[key] = True

        ctx.update(
            {
                "year": year_obj,
                # Plantings overview
                "total_plantings": all_plantings.count(),
                "completed_plantings": completed.count(),
                "failed_plantings": failed.count(),
                "skipped_plantings": skipped.count(),
                "failure_rate": (failed.count() / planned.count() * 100 if planned.count() else 0),
                # Space
                "total_planned_bf": total_planned_bf,
                "total_actual_bf": total_actual_bf,
                # Yield
                "planned_yield_total": planned_yield_total,
                "actual_yield_total": actual_yield_total,
                "yield_attainment": (
                    actual_yield_total / planned_yield_total * 100 if planned_yield_total else None
                ),
                # Revenue
                "total_revenue": total_revenue,
                "annual_target": annual_target,
                "revenue_attainment": (
                    total_revenue / annual_target * 100 if annual_target else None
                ),
                "revenue_gap": total_revenue - annual_target,
                "revenue_per_bf": (
                    total_revenue / total_actual_bf if total_actual_bf else Decimal("0")
                ),
                # Labor
                "total_harvest_hours": total_harvest_hours,
                "revenue_per_harvest_hour": revenue_per_harvest_hour,
                # Diversity
                "unique_crops": len(unique_crops),
                "crop_types": sorted(crop_types),
                "botanical_families": sorted(botanical_families),
                # Performers
                "top_10_crops": top_10,
                "bottom_10_crops": list(reversed(bottom_10)),
                # For rotation update UI
                "rotation_updates": len(rotation_updates),
            }
        )
        return ctx
