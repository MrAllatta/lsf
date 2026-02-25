# reference/models.py
from django.db import models

class CropInfo(models.Model):
    name = models.CharField(max_length=100, unique=True)
    crop_type = models.CharField(max_length=50)  # "Tomatoes", "Roots", etc.
    botanical_family = models.CharField(max_length=50, blank=True)
    propagation_type = models.CharField(
        max_length=20,
        choices=[('seed', 'Seed'), ('vegetative_clove', 'Clove'),
                 ('vegetative_tuber', 'Tuber'), ('vegetative_slip', 'Slip')],
        default='seed'
    )
    is_perennial = models.BooleanField(default=False)
    fresh_or_storage = models.CharField(
        max_length=10, choices=[('fresh', 'Fresh'), ('storage', 'Storage')]
    )
    storage_weeks = models.PositiveIntegerField(default=0)
    harvest_unit = models.CharField(max_length=20)  # "pounds", "bunches", "each"
    avg_unit_weight = models.DecimalField(max_digits=5, decimal_places=2)
    units_per_bin = models.PositiveIntegerField(null=True, blank=True)
    harvest_bin = models.CharField(max_length=50, blank=True)
    harvest_tools = models.CharField(max_length=100, blank=True)
    harvest_rate_per_hour = models.PositiveIntegerField(null=True, blank=True)
    
    # Nursery
    nursery_weeks = models.PositiveIntegerField(default=0)
    weeks_until_pot_up = models.PositiveIntegerField(default=0)
    pot_up_tray_size = models.PositiveIntegerField(null=True, blank=True)
    seeded_tray_size = models.PositiveIntegerField(null=True, blank=True)
    seeds_per_cell = models.PositiveIntegerField(default=1)
    thinned_plants = models.PositiveIntegerField(default=0)
    seeds_per_ounce = models.DecimalField(max_digits=10, decimal_places=1, 
                                          null=True, blank=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class BlockType(models.TextChoices):
    FIELD = 'field', 'Field'
    HIGH_TUNNEL = 'high_tunnel', 'High Tunnel'
    GREENHOUSE = 'greenhouse', 'Greenhouse'


class Block(models.Model):
    name = models.CharField(max_length=20, unique=True)
    block_type = models.CharField(max_length=20, choices=BlockType.choices)
    num_beds = models.PositiveIntegerField()
    bed_width_feet = models.DecimalField(max_digits=4, decimal_places=1)
    bedfeet_per_bed = models.PositiveIntegerField()
    walk_route_order = models.PositiveIntegerField(default=0)
    
    @property
    def total_bedfeet(self):
        return self.num_beds * self.bedfeet_per_bed
    
    @property
    def square_feet(self):
        return self.total_bedfeet * self.bed_width_feet
    
    class Meta:
        ordering = ['walk_route_order', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.get_block_type_display()})"


class CropByseason(models.Model):
    crop = models.ForeignKey(CropInfo, on_delete=models.CASCADE,
                             related_name='season_profiles')
    block_type = models.CharField(max_length=20, choices=BlockType.choices)
    
    field_week_start = models.PositiveIntegerField()
    field_week_end = models.PositiveIntegerField()
    
    total_yield_per_bedfoot = models.DecimalField(max_digits=6, decimal_places=2)
    harvest_weeks = models.PositiveIntegerField()
    dtm_days = models.PositiveIntegerField()
    
    rows_per_bed = models.PositiveIntegerField()
    ds_seed_rate = models.PositiveIntegerField(null=True, blank=True)
    tp_inrow_spacing = models.DecimalField(max_digits=5, decimal_places=2, 
                                           null=True, blank=True)
    seeder_settings = models.CharField(max_length=200, blank=True)
    trellis_system = models.CharField(max_length=100, blank=True)
    mulch = models.CharField(max_length=50, blank=True)
    row_cover = models.CharField(max_length=50, blank=True)
    irrigation = models.CharField(max_length=50, blank=True)
    
    @property
    def wtm_weeks(self):
        return math.ceil(self.dtm_days / 7)
    
    @property
    def weekly_yield_per_bedfoot(self):
        if self.harvest_weeks:
            return self.total_yield_per_bedfoot / self.harvest_weeks
        return Decimal('0')
    
    class Meta:
        unique_together = ['crop', 'block_type']
        ordering = ['crop__name', 'block_type']
    
    def __str__(self):
        return f"{self.crop.name} / {self.get_block_type_display()}"
