"""core/management/commands/clone_plan.py"""

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from isoweek import Week

from planning.models import PlanningYear, Planting, NurseryEvent, HarvestEvent
from core.models import RotationHistory


class Command(BaseCommand):
    help = "Clone a planning year as starting point for the next year"

    def add_arguments(self, parser):
        parser.add_argument("source_year", type=int)
        parser.add_argument("target_year", type=int)
        parser.add_argument(
            "--include-actuals",
            action="store_true",
            help="Copy actual yield data as reference (not as plan)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        source_year = options["source_year"]
        target_year = options["target_year"]
        year_diff = target_year - source_year

        try:
            source = PlanningYear.objects.get(year=source_year)
        except PlanningYear.DoesNotExist:
            self.stderr.write(f"Source year {source_year} not found.\n")
            return

        # Create target year
        target, created = PlanningYear.objects.get_or_create(
            year=target_year,
            defaults={
                "status": "planning",
                "overplant_factor": source.overplant_factor,
            },
        )

        if not created and target.plantings.exists():
            self.stderr.write(
                f"Target year {target_year} already has "
                f"{target.plantings.count()} plantings. "
                f"Use --force to overwrite (not implemented).\n"
            )
            return

        # Get source plantings (exclude revisions, failed, skipped)
        source_plantings = (
            Planting.objects.filter(
                planning_year=source,
            )
            .exclude(status__in=["revised", "failed", "skipped"])
            .select_related("crop", "crop_season", "block")
            .order_by("block__name", "bed_start", "planned_plant_date")
        )

        # Check rotation
        rotation_warnings = []

        cloned = 0
        for sp in source_plantings:
            # Shift dates by year_diff years
            # Use ISO week to maintain week alignment
            source_week = sp.planned_plant_date.isocalendar()[1]
            new_plant_date = Week(target_year, source_week).monday()

            # Recalculate harvest dates from crop_season
            new_first_harvest = new_plant_date + timedelta(days=sp.crop_season.dtm_days)
            new_last_harvest = new_first_harvest + timedelta(weeks=sp.crop_season.harvest_weeks - 1)

            # Check rotation
            family = sp.crop.botanical_family
            if family:
                from core.models import RotationRule

                rule = RotationRule.objects.filter(botanical_family=family).first()

                recent = RotationHistory.objects.filter(
                    block=sp.block,
                    botanical_family=family,
                    year__gte=target_year - (rule.min_gap_years if rule else 3),
                    year__lt=target_year,
                ).exists()

                if recent and rule:
                    rotation_warnings.append(
                        f"  ⚠ {sp.crop.name} in {sp.block.name}: "
                        f"{family} rotation violation "
                        f"(min {rule.min_gap_years}yr gap)"
                    )

            # Determine planned yield — use actual if available and better
            planned_yield = sp.planned_total_yield
            if options["include_actuals"] and sp.actual_total_yield:
                # Use actual yield per bedfoot for next year's projection
                actual_yield_per_bf = (
                    sp.actual_total_yield / sp.planned_bedfeet
                    if sp.planned_bedfeet
                    else sp.crop_season.total_yield_per_bedfoot
                )
                planned_yield = actual_yield_per_bf * sp.planned_bedfeet

            new_planting = Planting.objects.create(
                planning_year=target,
                crop=sp.crop,
                crop_season=sp.crop_season,
                variety=sp.variety,
                block=sp.block,
                bed_start=sp.bed_start,
                bed_end=sp.bed_end,
                planned_bedfeet=sp.planned_bedfeet,
                planned_plant_date=new_plant_date,
                planned_first_harvest_date=new_first_harvest,
                planned_last_harvest_date=new_last_harvest,
                planned_total_yield=planned_yield,
                succession_group=sp.succession_group,
                status="planned",
                notes=f"Cloned from {source_year} planting #{sp.id}",
            )

            # Generate nursery and harvest events
            new_planting.generate_nursery_events()
            new_planting.generate_harvest_events()

            cloned += 1

        # Update rotation history from source year
        families_by_block = {}
        for sp in source_plantings:
            family = sp.crop.botanical_family
            if family and sp.status not in ("skipped", "failed"):
                key = (sp.block_id, family)
                families_by_block[key] = True

        for block_id, family in families_by_block:
            RotationHistory.objects.update_or_create(
                block_id=block_id,
                year=source_year,
                defaults={"botanical_family": family},
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nCloned {cloned} plantings from {source_year} " f"to {target_year}.\n"
            )
        )

        if rotation_warnings:
            self.stdout.write(
                self.style.WARNING(f"\nRotation warnings ({len(rotation_warnings)}):\n")
            )
            for warning in rotation_warnings:
                self.stdout.write(self.style.WARNING(warning + "\n"))
            self.stdout.write("\nThese plantings were cloned but may need " "block reassignment.\n")

        # Summary
        self.stdout.write(f"\nTarget year {target_year} now has:\n")
        self.stdout.write(f"  {target.plantings.count()} plantings\n")
        self.stdout.write(
            f"  {NurseryEvent.objects.filter(planting__planning_year=target).count()}"
            f" nursery events\n"
        )
        self.stdout.write(
            f"  {HarvestEvent.objects.filter(planting__planning_year=target).count()}"
            f" harvest events\n"
        )

        total_bf = sum(p.planned_bedfeet for p in target.plantings.all())
        self.stdout.write(f"  {total_bf:,} total bedfeet planned\n")
