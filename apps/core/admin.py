from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import FarmUser


@admin.register(FarmUser)
class FarmUserAdmin(UserAdmin):
    pass


# Register your models here.
