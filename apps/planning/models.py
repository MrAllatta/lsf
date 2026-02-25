"""planning/models.py"""

from django.db import models
from decimal import Decimal
from datetime import date, timedelta
from django.contrib.postgres.fields import ArrayField
from reference.models import CropInfo


class PlanningYear(models.Model):
    year = models.PositiveIntegerField(unique=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("planning", "Planning"),
            ("active", "Active"),
            ("complete", "Complete"),
            ("archived", "Archived"),
        ],
        default="planning",
    )
    overplant_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.10"))

    def __str__(self):
        return f"{self.year} ({self.get_status_display()})"


class PlantingStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    SEEDED = "seeded", "Seeded (nursery)"
    PLANTED = "planted", "Planted"
    GROWING = "growing", "Growing"
    HARVESTING = "harvesting", "Harvesting"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    REVISED = "revised", "Revised"


class Planting(models.Model):
    planning_year = models.ForeignKey(
        PlanningYear, on_delete=models.CASCADE, related_name="plantings"
    )
    revision_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="revisions"
    )
    succession_group = models.CharField(max_length=50, blank=True)

    crop = models.ForeignKey(CropInfo, on_delete=models.PROTECT)
    crop_season = models.ForeignKey("reference.CropBySeason", on_delete=models.PROTECT)
    variety = models.CharField(max_length=100, blank=True)
    block = models.ForeignKey("reference.Block", on_delete=models.PROTECT)
    bed_start = models.PositiveIntegerField()
    bed_end = models.PositiveIntegerField()

    # Planned
    planned_bedfeet = models.PositiveIntegerField()
    planned_plant_date = models.DateField()
    planned_first_harvest_date = models.DateField()
    planned_last_harvest_date = models.DateField()
    planned_total_yield = models.DecimalField(max_digits=10, decimal_places=2)

    # Actual
    actual_bedfeet = models.PositiveIntegerField(null=True, blank=True)
    actual_plant_date = models.DateField(null=True, blank=True)
    actual_first_harvest_date = models.DateField(null=True, blank=True)
    actual_last_harvest_date = models.DateField(null=True, blank=True)
    actual_total_yield = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    status = models.CharField(
        max_length=20, choices=PlantingStatus.choices, default=PlantingStatus.PLANNED
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Auto-calculate planned fields from crop_season
        if not self.planned_first_harvest_date and self.planned_plant_date:
            self.planned_first_harvest_date = self.planned_plant_date + timedelta(
                days=self.crop_season.dtm_days
            )
        if not self.planned_last_harvest_date and self.planned_first_harvest_date:
            self.planned_last_harvest_date = self.planned_first_harvest_date + timedelta(
                weeks=self.crop_season.harvest_weeks - 1
            )
        if not self.planned_total_yield:
            self.planned_total_yield = (
                self.planned_bedfeet * self.crop_season.total_yield_per_bedfoot
            )
        super().save(*args, **kwargs)

    def generate_nursery_events(self):
        """Create nursery events from crop info."""
        if self.crop.nursery_weeks == 0:
            return

        seed_date = self.planned_plant_date - timedelta(weeks=self.crop.nursery_weeks)
        NurseryEvent.objects.create(
            planting=self,
            event_type="seed",
            planned_date=seed_date,
            # tray calculations here...
        )

        if self.crop.weeks_until_pot_up:
            pot_up_date = seed_date + timedelta(weeks=self.crop.weeks_until_pot_up)
            NurseryEvent.objects.create(
                planting=self,
                event_type="pot_up",
                planned_date=pot_up_date,
            )

            NurseryEvent.objects.create(
                planting=self,
                event_type="transplant",
                planned_date=self.planned_plant_date,
            )

    def generate_harvest_events(self):
        """Create planned weekly harvest events."""
        weekly_yield = self.crop_season.weekly_yield_per_bedfoot * self.planned_bedfeet
        current = self.planned_first_harvest_date
        while current <= self.planned_last_harvest_date:
            HarvestEvent.objects.create(
                planting=self,
                planned_date=current,
                planned_quantity=weekly_yield,
                planned_units=self.crop.harvest_unit,
            )
            current += timedelta(weeks=1)

    class Meta:
        ordering = ["planned_plant_date", "block__name"]


class NurseryEvent(models.Model):
    EVENT_TYPES = [
        ("seed", "Seed"),
        ("pot_up", "Pot Up"),
        ("harden", "Harden Off"),
        ("transplant", "Transplant"),
    ]

    planting = models.ForeignKey(Planting, on_delete=models.CASCADE, related_name="nursery_events")
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)

    planned_date = models.DateField()
    planned_tray_count = models.PositiveIntegerField(null=True, blank=True)
    planned_tray_size = models.PositiveIntegerField(null=True, blank=True)

    actual_date = models.DateField(null=True, blank=True)
    actual_tray_count = models.PositiveIntegerField(null=True, blank=True)
    actual_tray_size = models.PositiveIntegerField(null=True, blank=True)
    actual_germination_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["planned_date", "planting"]

    @property
    def planned_week(self):
        return self.planned_date.isocalendar()[1]

    @property
    def is_complete(self):
        return self.actual_date is not None


class HarvestEvent(models.Model):
    planting = models.ForeignKey(Planting, on_delete=models.CASCADE, related_name="harvest_events")
    planned_date = models.DateField()

    planned_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    planned_units = models.CharField(max_length=20)

    actual_date = models.DateField(null=True, blank=True)
    actual_quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    actual_units = models.CharField(max_length=20, blank=True)
    actual_bins = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    actual_bin_type = models.CharField(max_length=50, blank=True)
    actual_hours = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    actual_workers = models.PositiveIntegerField(null=True, blank=True)

    quality_grade = models.CharField(
        max_length=20,
        blank=True,
        choices=[("prime", "Prime"), ("seconds", "Seconds"), ("mixed", "Mixed")],
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["planned_date", "planting"]

    @property
    def planned_week(self):
        return self.planned_date.isocalendar()[1]

    def record_bins(self, bin_count, bin_type=None):
        """Convert bin count to quantity using crop info."""
        self.actual_bins = bin_count
        if bin_type:
            self.actual_bin_type = bin_type
        else:
            self.actual_bin_type = self.planting.crop.harvest_bin

        units_per_bin = self.planting.crop.units_per_bin
        if units_per_bin:
            self.actual_quantity = bin_count * units_per_bin
            self.actual_units = self.planting.crop.harvest_unit
        self.actual_date = date.today()
        self.save()


class CropSalesFormat(models.Model):
    crop = models.ForeignKey(CropInfo, on_delete=models.CASCADE, related_name="sales_formats")
    product_name = models.CharField(max_length=100)
    sale_price = models.DecimalField(max_digits=8, decimal_places=2)
    sale_unit = models.CharField(max_length=20)  # "each", "pound", "bunch", "pint", "bag"
    harvest_qty_per_sale_unit = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("1.00")
    )
    sku = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["crop__name", "product_name"]

    def __str__(self):
        return f"{self.product_name} @ ${self.sale_price}/{self.sale_unit}"


class SalesChannel(models.Model):
    name = models.CharField(max_length=100)
    days_of_week = ArrayField(
        models.CharField(max_length=10), default=list
    )  # PostgreSQL array field
    start_week = models.PositiveIntegerField()
    end_week = models.PositiveIntegerField()
    weekly_target = models.DecimalField(max_digits=10, decimal_places=2)
    is_csa = models.BooleanField(default=False)
    allocation_priority = models.PositiveIntegerField(default=10)

    @property
    def num_weeks(self):
        if self.end_week >= self.start_week:
            return self.end_week - self.start_week + 1
        return (52 - self.start_week + 1) + self.end_week

    @property
    def annual_target(self):
        return self.weekly_target * self.num_weeks

    class Meta:
        ordering = ["allocation_priority", "name"]

    def __str__(self):
        return self.name
