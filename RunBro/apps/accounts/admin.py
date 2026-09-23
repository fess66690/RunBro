from django.contrib import admin

from django.contrib import admin

from .models import RunnerProfile


@admin.register(RunnerProfile)
class RunnerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_vdot', 'experience_months', 'goal_race', 'created_at')
    list_filter = ('goal_race', 'experience_months')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Пользователь', {
            'fields': ('user',)
        }),
        ('Физиология', {
            'fields': ('birth_year', 'resting_hr', 'experience_months')
        }),
        ('Текущий уровень', {
            'fields': ('current_vdot',)
        }),
        ('Цель', {
            'fields': ('goal_race', 'goal_time_seconds', 'target_vdot')
        }),
        ('Служебное', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
