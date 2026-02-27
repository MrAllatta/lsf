"""core/models.py"""

from django.db import models
from django.contrib.auth.models import AbstractUser


class FarmUser(AbstractUser):
    """Custom user for future extension."""

    pass


class RotationRule(models.Model):
    botanical_family = models.CharField(max_length=50, unique=True)
    min_gap_years = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.botanical_family}: {self.min_gap_years}yr minimum"


class RotationHistory(models.Model):
    block = models.ForeignKey(
        "reference.Block", on_delete=models.CASCADE, related_name="rotation_history"
    )
    year = models.PositiveIntegerField()
    botanical_family = models.CharField(max_length=50)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ["block", "year"]
        ordering = ["block__name", "-year"]


class GrowingSeasonEvent(models.Model):
    year = models.PositiveIntegerField()
    week = models.PositiveIntegerField()
    event_date = models.DateField()
    event_name = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["year", "week"]
        unique_together = ["year", "week", "event_date"]
